Colors in Context
=================

Code and supplementary material for

* [Colors in Context: A Pragmatic Neural Model for Grounded Language
Understanding (TACL 2017)](https://arxiv.org/abs/1703.10186)
* Generating Bilingual Pragmatic Color References (NAACL 2018)

See http://cocolab.stanford.edu/datasets/colors.html for quick links to the
datasets released with these papers.

Dependencies
------------

You'll first need Python 2.7. Creating and activating a new virtualenv or
Anaconda environment is recommended. Then run this script to download data and
Python package dependencies:

    ./dependencies

The dependencies script is reasonably simple, so if this fails, it should be
possible to look at the script and manually perform the actions it specifies.

This code is written to be run on a Linux system; we've also tested it on Mac
OS X (but see "Troubleshooting": missing g++ will cause the program to run
impossibly slowly). The code is unlikely to run on Windows, but you're welcome
to try.

Running experiments
-------------------

### Bilingual Color References

To re-run pre-trained monolingual and bilingual agents from Table 1, you can
use the following commands:

    python run_experiment.py --config models/en_l1.config.json        # (en: en)
    python run_experiment.py --config models/biling_l1_en.config.json # (en: en+zh)
    python run_experiment.py --config models/zh_l1.config.json        # (zh: zh)
    python run_experiment.py --config models/biling_l1_zh.config.json # (zh: en+zh)

Look for `eval.accuracy.mean` in the output to compare with Table 2. This
command uses dev set results by default; add `--data_source filtered_test` to
reproduce the test set results instead.

### Colors in Context

To re-run the base listener L0 from the paper (Table 3) with pre-trained
models, use:

    python run_experiment.py --config models/l0.config.json

Re-running the other experiments requires first constructing the "quickload"
file for the base speaker:

    python quickpickle.py --config models/s0.config.json

Then run the Lb model (again, use `--data_source filtered_test` to run on the
test set):

    python run_experiment.py --config models/lb.config.json

This is required before you can run all of the other models. It is also the
slowest part, and can take several days on a CPU; using a properly-configured
GPU usually takes about 19 hours and can be used by passing `--device gpu0` to
**both** the `quickpickle.py` and `run_experiment.py` commands above. See

    http://deeplearning.net/software/theano/tutorial/using_gpu.html

for necessary configuration.

The output of this file is a 230MB file, `runs/lb/grids.0.jsons.gz`, which
contains half of the information needed to run all of the other experiments
without rerunning the model. The other half is scores of the sampled utterances
using the S0 model. To generate these (~6 hours on CPU, usually less than 1
hour on GPU):

    python s0_score.py --config models/s0.config.json \
                       --grids_file runs/lb/grids.0.jsons.gz

Once this is done, the remaining experiments should be very fast to run. They
use a separate script that loads the grids files from the other runs:

    python blending.py --config models/l1.config.json
    python blending.py --config models/l2.config.json
    python blending.py --config models/la.config.json
    python blending.py --config models/le.config.json

The results of the experiment, including predictions and log-likelihood scores,
will all be logged to the directory

    runs/lb

To retrain any models for either paper from scratch, add `--load ''` to the
`run_experiment.py` command. Like the Lb step, GPU is recommended here; for
training, the difference in speed can be dramatic (2 hours vs. days).

Troubleshooting
---------------

* Error messages of the form

    `error: argument --...: invalid int value: '<pyhocon.config_tree.NoneValue
    object at ...>'`

  should be solved by making sure you're using pyhocon version 0.3.18; if this
  doesn't work, supplying a number for the argument should fix it. We've seen
  this with the arguments `--train_size`, `--test_size`, and
  `--direct_min_score`; to fix these, add:

    --train_size 10000000 --test_size 10000000 --direct_min_score 9999

* A warning message of the form

    `WARNING (theano.configdefaults): g++ not detected ! Theano will be unable
    to execute optimized C-implementations (for both CPU and GPU) and will
    default to Python implementations. Performance will be severely degraded.
    To remove this warning, set Theano flags cxx to an empty string.`

  should be heeded. Otherwise even just running prediction will take a very
  long time (days). Check whether you can run `g++` from a terminal, or try
  changing the Theano cxx flag (in ~/.theanorc) to point to an alternative C++
  compiler on the system.

* If retrying a run after a previous error, you'll need to add the option
  `--overwrite` (or specify a different output directory with `--run_dir
  DIR`).  The program will remind you of this if you forget.

* Very low accuracies (`dev.accuracy.mean` < 0.5) could indicate
  incompatible changes in the version of Lasagne or Theano (we've seen this
  with Lasagne 0.1). We've reproduced our main results using the development
  versions of Theano and Lasagne as of June 2, 2016:

    * https://github.com/Theano/Theano/tree/0693ce052725a15b502068a1490b0637216feb00
    * https://github.com/Lasagne/Lasagne/tree/8fe645d28b66f991d547e9b6a314251b8e84446a
