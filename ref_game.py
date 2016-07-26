import numpy as np
from scipy.misc import logsumexp
from sklearn.linear_model import LogisticRegression

from stanza.monitoring import progress
from stanza.research import config, instance, iterators
from stanza.research.learner import Learner

from neural import sample
from tokenizers import TOKENIZERS
from vectorizers import SequenceVectorizer, COLOR_REPRS


class ExhaustiveS1Learner(Learner):
    def __init__(self, base=None):
        options = config.options()
        if base is None:
            self.base = learners.new(options.exhaustive_base_learner)
        else:
            self.base = base

    def train(self, training_instances, validation_instances=None, metrics=None):
        return self.base.train(training_instances=training_instances,
                               validation_instances=validation_instances, metrics=metrics)

    @property
    def num_params(self):
        return self.base.num_params

    def predict_and_score(self, eval_instances, random=False, verbosity=0):
        options = config.options()
        predictions = []
        scores = []

        all_utts = self.base.seq_vec.tokens
        sym_vec = vectorizers.SymbolVectorizer()
        sym_vec.add_all(all_utts)
        prior_scores = self.prior_scores(all_utts)

        base_is_listener = (type(self.base) in listener.LISTENERS.values())

        true_batch_size = options.listener_eval_batch_size / len(all_utts)
        batches = iterators.iter_batches(eval_instances, true_batch_size)
        num_batches = (len(eval_instances) - 1) // true_batch_size + 1

        if options.verbosity + verbosity >= 2:
            print('Testing')
        progress.start_task('Eval batch', num_batches)
        for batch_num, batch in enumerate(batches):
            progress.progress(batch_num)
            batch = list(batch)
            context = len(batch[0].alt_inputs) if batch[0].alt_inputs is not None else 0
            if context:
                output_grid = [(instance.Instance(utt, color)
                                if base_is_listener else
                                instance.Instance(color, utt))
                               for inst in batch for color in inst.alt_inputs
                               for utt in sym_vec.tokens]
                assert len(output_grid) == context * len(batch) * len(all_utts), \
                    'Context must be the same number of colors for all examples'
                true_indices = np.array([inst.input for inst in batch])
            else:
                output_grid = [(instance.Instance(utt, inst.input)
                                if base_is_listener else
                                instance.Instance(inst.input, utt))
                               for inst in batch for utt in sym_vec.tokens]
                true_indices = sym_vec.vectorize_all([inst.input for inst in batch])
                if len(true_indices.shape) == 2:
                    # Sequence vectorizer; we're only using single tokens for now.
                    true_indices = true_indices[:, 0]
            scores = self.base.score(output_grid, verbosity=verbosity)
            if context:
                log_probs = np.array(scores).reshape((len(batch), context, len(all_utts)))
                orig_log_probs = log_probs[np.arange(len(batch)), true_indices, :]
                # Renormalize over only the context colors, and extract the score of
                # the true color.
                log_probs -= logsumexp(log_probs, axis=1)[:, np.newaxis, :]
                log_probs = log_probs[np.arange(len(batch)), true_indices, :]
            else:
                log_probs = np.array(scores).reshape((len(batch), len(all_utts)))
                orig_log_probs = log_probs
            assert log_probs.shape == (len(batch), len(all_utts))
            # Add in the prior scores, if used (S1 \propto L0 * P)
            if prior_scores is not None:
                log_probs = log_probs + 0.5 * prior_scores
            if options.exhaustive_base_weight:
                w = options.exhaustive_base_weight
                log_probs = w * orig_log_probs + (1.0 - w) * log_probs
            # Normalize across utterances. Note that the listener returns probability
            # densities over colors.
            log_probs -= logsumexp(log_probs, axis=1)[:, np.newaxis]
            if random:
                pred_indices = sample(np.exp(log_probs))
            else:
                pred_indices = np.argmax(log_probs, axis=1)
            predictions.extend(sym_vec.unvectorize_all(pred_indices))
            scores.extend(log_probs[np.arange(len(batch)), true_indices].tolist())
        progress.end_task()

        return predictions, scores

    def dump(self, outfile):
        return self.base.dump(outfile)

    def load(self, infile):
        return self.base.load(infile)

    def prior_scores(self, utts):
        # Don't use prior scores by default
        pass


class ExhaustiveS1PriorLearner(ExhaustiveS1Learner):
    def __init__(self, prior_counter, base=None):
        self.prior_counter = prior_counter
        self.denominator = sum(prior_counter.values())
        super(ExhaustiveS1PriorLearner, self).__init__(base=base)

    def prior_scores(self, utts):
        return np.log(np.array([self.prior_counter[u] for u in utts])) - np.log(self.denominator)


class DirectRefGameLearner(Learner):
    def __init__(self, base=None):
        options = config.options()
        if base is None:
            self.base = learners.new(options.direct_base_learner)
        else:
            self.base = base

    def train(self, training_instances, validation_instances=None, metrics=None):
        return self.base.train(training_instances=training_instances,
                               validation_instances=validation_instances, metrics=metrics)

    @property
    def num_params(self):
        return self.base.num_params

    def predict_and_score(self, eval_instances, random=False, verbosity=0):
        options = config.options()
        predictions = []
        scores = []
        base_is_listener = (type(self.base) in listener.LISTENERS.values())
        assert options.listener, 'Eval data should be listener data for DirectRefGameLearner'

        true_batch_size = options.listener_eval_batch_size / options.num_distractors
        batches = iterators.iter_batches(eval_instances, true_batch_size)
        num_batches = (len(eval_instances) - 1) // true_batch_size + 1

        if options.verbosity + verbosity >= 2:
            print('Testing')
        progress.start_task('Eval batch', num_batches)
        for batch_num, batch in enumerate(batches):
            progress.progress(batch_num)
            batch = list(batch)
            assert batch[0].alt_outputs, 'No context given for direct listener testing'
            context = len(batch[0].alt_outputs)
            output_grid = [instance.Instance(inst.input, color)
                           if base_is_listener else
                           instance.Instance(color, inst.input)
                           for inst in batch for color in inst.alt_outputs]
            assert len(output_grid) == context * len(batch), \
                'Context must be the same number of colors for all examples'
            true_indices = np.array([inst.output for inst in batch])
            grid_scores = self.base.score(output_grid, verbosity=verbosity)
            log_probs = np.array(grid_scores).reshape((len(batch), context))
            # Renormalize over only the context colors
            log_probs -= logsumexp(log_probs, axis=1)[:, np.newaxis]
            # Cap confidences to reasonable values
            if options.direct_min_score is not None and options.direct_min_score <= 0.0:
                log_probs = np.maximum(options.direct_min_score, log_probs)
                # Normalize again (so we always return log probabilities)
                log_probs -= logsumexp(log_probs, axis=1)[:, np.newaxis]
            assert log_probs.shape == (len(batch), context)
            pred_indices = np.argmax(log_probs, axis=1)
            predictions.extend(pred_indices.tolist())
            # Extract the score of the true color
            scores.extend(log_probs[np.arange(len(batch)), true_indices].tolist())
        progress.end_task()

        return predictions, scores

    def dump(self, outfile):
        return self.base.dump(outfile)

    def load(self, infile):
        return self.base.load(infile)


class LRContextListenerLearner(Learner):
    def train(self, training_instances, validation_instances=None, metrics=None):
        X, y = self._data_to_arrays(training_instances, init_vectorizer=True)
        self.mod = LogisticRegression(solver='lbfgs')
        self.mod.fit(X, y)

    @property
    def num_params(self):
        return np.prod(self.mod.coef_.shape) + np.prod(self.mod.intercept_.shape)

    def predict_and_score(self, eval_instances, random=False, verbosity=0):
        X, y = self._data_to_arrays(eval_instances)
        y = y.reshape((len(eval_instances), self.context_len))
        all_scores = self.mod.predict_log_proba(X)[:, 1].reshape((len(eval_instances),
                                                                  self.context_len))
        all_scores -= logsumexp(all_scores, axis=1)[:, np.newaxis]

        preds = all_scores.argmax(axis=1)
        scores = np.where(y, all_scores, 0).sum(axis=1)

        return preds.tolist(), scores.tolist()

    def _data_to_arrays(self, instances, inverted=False, init_vectorizer=False):
        self.get_options()

        get_i, get_o = (lambda inst: inst.input), (lambda inst: inst.output)
        get_desc, get_color = (get_o, get_i) if inverted else (get_i, get_o)
        get_alt_i, get_alt_o = (lambda inst: inst.alt_inputs), (lambda inst: inst.alt_outputs)
        get_alt_colors = get_alt_i if inverted else get_alt_o

        tokenize = TOKENIZERS[self.options.listener_tokenizer]
        tokenized = [tokenize(get_desc(inst)) for inst in instances]
        context_lens = [len(get_alt_colors(inst)) for inst in instances]

        if init_vectorizer:
            self.seq_vec = SequenceVectorizer()
            self.seq_vec.add_all(tokenized)

        unk_replaced = self.seq_vec.unk_replace_all(tokenized)

        if init_vectorizer:
            config.dump(unk_replaced, 'unk_replaced.train.jsons', lines=True)

            self.context_len = context_lens[0]

            color_repr = COLOR_REPRS[self.options.listener_color_repr]
            self.color_vec = color_repr(self.options.listener_color_resolution,
                                        hsv=self.options.listener_hsv)

        assert all(cl == self.context_len for cl in context_lens), (self.context_len, context_lens)

        padded = [(d + ['</s>'] * (self.seq_vec.max_len - len(d)))[:self.seq_vec.max_len]
                  for d in unk_replaced]
        colors = [c for inst in instances for c in get_alt_colors(inst)]
        labels = np.array([int(i == get_color(inst))
                           for inst in instances
                           for i in range(self.context_len)])

        desc_indices = self.seq_vec.vectorize_all(padded)
        desc_bow = -np.ones((desc_indices.shape[0], self.seq_vec.num_types))
        desc_bow[np.arange(desc_indices.shape[0])[:, np.newaxis], desc_indices] = 1.
        color_feats = self.color_vec.vectorize_all(colors)
        color_feats = color_feats.reshape((desc_indices.shape[0],
                                           self.context_len,
                                           color_feats.shape[1]))
        feats = np.einsum('ij,ick->icjk', desc_bow, color_feats)
        feats = feats.reshape((desc_indices.shape[0] * self.context_len,
                               desc_bow.shape[1] * color_feats.shape[2]))

        return feats, labels

    def get_options(self):
        if not hasattr(self, 'options'):
            self.options = config.options()


import learners
import listener
import vectorizers


parser = config.get_options_parser()
parser.add_argument('--exhaustive_base_learner', default='Listener',
                    choices=learners.LEARNERS.keys(),
                    help='The name of the model to use as the L0 for exhaustive enumeration-based '
                         'speaker models.')
parser.add_argument('--exhaustive_base_weight', default=0.0, type=float,
                    help='Weight given to the base agent for the exhaustive RSA model. The RSA '
                         "agent's weight will be 1 - exhaustive_base_weight.")
parser.add_argument('--direct_base_learner', default='Listener',
                    choices=learners.LEARNERS.keys(),
                    help='The name of the model to use as the level-0 agent for direct score-based '
                         'listener models.')
parser.add_argument('--direct_min_score', default=None, type=float,
                    help='The log likelihood of the base model will be capped from below to this '
                         'value. This prevents extreme-confidence wrong decisions, and '
                         'is roughly equivalent to postulating an a priori probability that a '
                         'target in the dataset is chosen uniformly at random. None or positive '
                         'values will be interpreted as no cap.')
