import warnings
from shutil import get_terminal_size

import pandas as pd
from click import Choice
from click import File
from click import Path
from click import argument
from click import confirm
from click import echo
from click import get_current_context
from click import group
from click import option
from colorama import Fore

from coinflip import generators
from coinflip.randtests import __all__ as randtest_names
from coinflip.randtests._exceptions import NonBinarySequenceError
from coinflip.randtests._exceptions import TestError
from coinflip.randtests._pprint import dim
from coinflip.randtests._pprint import pretty_seq
from coinflip.report import write_report
from coinflip.store import *
from coinflip.tests_runner import *

__all__ = [
    "load",
    "rm",
    "rm_all",
    "ls",
    "cat",
    "run",
    "example_run",
    "local_run",
    "report",
]

# ------------------------------------------------------------------------------
# Pretty printing


warn_txt = Fore.YELLOW + "WARN" + Fore.RESET
err_txt = Fore.RED + "ERR!" + Fore.RESET


def formatwarning(msg, *args, **kwargs):
    """Pretty print warnings"""
    return dim(f"{warn_txt} {msg}\n")


# Monkey patch python's warning module to use our formatting
warnings.formatwarning = formatwarning


def echo_err(e: Exception):
    """Pretty print exceptions"""
    line = f"{err_txt} {e}"
    echo(line, err=True)


# TODO descriptions of the series e.g. length
def echo_series(series):
    """Pretty print series that contain binary data"""
    size = get_terminal_size()
    cols = min(size.columns, 80)

    echo(pretty_seq(series, cols))


# ------------------------------------------------------------------------------
# Autocompletion


def get_stores(ctx, args, incomplete):
    """Completition for store names"""
    stores = list(list_stores())
    if incomplete is None:
        return stores
    else:
        for name in stores:
            if incomplete in name:
                yield name


# TODO extend Choice to use echo_err and newline-delimit lists
dtype_choice = Choice(TYPES.keys())
test_choice = Choice(randtest_names)

# ------------------------------------------------------------------------------
# Help option

CONTEXT_SETTINGS = {"help_option_names": ["-h", "--help"]}

help_msg = {
    "name": "Specify name of the store.",
    "dtype": "Specify data type of the data.",
    "test": "Specify single test to run on data.",
}

# ------------------------------------------------------------------------------
# Prompting


def infer_store():
    """Finds the last initialised store and prompts on using it"""
    try:
        store = find_latest_store()
    except NoLatestStoreRecordedError:
        ctx = get_current_context()
        ctx.fail("Missing argument 'STORE'.")

    msg = (
        "No STORE argument provided\n"
        f"\tThe most recent STORE to be initialised is '{store}'\n"
        "\tPass it as the STORE argument?"
    )
    if confirm(msg):
        return store
    else:
        exit(0)


# ------------------------------------------------------------------------------
# Commands


@group(context_settings=CONTEXT_SETTINGS)
def main():
    """Randomness tests for RNG output.

    Output of random number generators can be parsed and serialised into a
    test-ready format via the load command. The data is saved in a folder, which
    coinflip refers to as a "store". This store is located in the local data
    directory, but can be easily accessed via the store's name in coinflip
    commands.

    Randomness tests can then be ran over the store's data via the run command.
    Rich documents explaining the test results can be produced via the report
    command.
    """


@main.command()
@argument("data", type=File("r"))
@option("-n", "--name", type=str, help=help_msg["name"])
@option("-d", "--dtype", type=dtype_choice, help=help_msg["dtype"], metavar="<dtype>")
@option(
    "-o", "--overwrite", is_flag=True, help="Overwrite existing store with same name."
)
def load(data, name, dtype, overwrite):
    """Loads DATA into a store.

    DATA is a newline-delimited text file which contains output of a random
    number generator. The contents are parsed, serialised and saved in local
    data.

    The stored data can then be applied the randomness tests via the run
    command, where the results of which are also saved.
    """
    try:
        store_data(data, name=name, dtype_str=dtype, overwrite=overwrite)
    except (DataParsingError, NonBinarySequenceError, StoreError) as e:
        echo_err(e)
        exit(1)

    try:
        store = find_latest_store()
        series = get_data(store)
        echo_series(series)
    except (NoLatestStoreRecordedError, StoreNotFoundError):
        exit(0)


@main.command()
@argument("store", autocompletion=get_stores)
def rm(store):
    """Delete STORE."""
    drop(store)


@main.command()
def rm_all():
    """Delete all stores."""
    for store in list_stores():
        drop(store)


@main.command()
def ls():
    """List all stores."""
    for store in list_stores():
        echo(store)


@main.command()
@argument("store", autocompletion=get_stores, required=False, metavar="STORE")
def cat(store):
    """Print contents of data in STORE."""
    if not store:
        store = infer_store()

    try:
        series = get_data(store)
        echo_series(series)
    except StoreNotFoundError as e:
        echo_err(e)
        exit(1)


# TODO save per result
@main.command()
@argument("store", autocompletion=get_stores, required=False, metavar="STORE")
@option("-t", "--test", type=test_choice, help=help_msg["test"], metavar="<test>")
def run(store, test):
    """Run randomness tests on data in STORE.

    Results of the tests run are saved in STORE, which can be compiled into
    a rich document via the report command.
    """
    if not store:
        store = infer_store()

    try:
        series = get_data(store)
    except StoreNotFoundError as e:
        echo_err(e)
        exit(1)

    try:
        if not test:
            results = {}
            for name, result, e in run_all_tests(series):
                if e:
                    echo_err(e)
                else:
                    results[name] = result

            store_results(store, results)
            echo("Results stored!")
        else:
            try:
                result = run_test(series, test)
                store_result(store, test, result)
                echo("Result stored!")

            except TestError as e:
                echo_err(e)
                exit(1)

    except NonBinarySequenceError as e:
        echo_err(e)
        exit(1)


@main.command()
@option(
    "-e",
    "--example",
    type=Choice(generators.__all__),
    default="python",
    help="Example binary output to use.",
    metavar="<example>",
)
@option("-n", "--length", type=int, default=512, help="Length of binary output.")
@option("-t", "--test", type=test_choice, help=help_msg["test"], metavar="<test>")
def example_run(example, length, test):
    """Run randomness tests on example data."""
    generator_func = getattr(generators, example)
    generator = generator_func()

    series = pd.Series(next(generator) for _ in range(length))
    series = series.infer_objects()
    echo_series(series)
    echo()

    try:
        if not test:
            for name, result, e in run_all_tests(series):
                if e:
                    echo_err(e)

        else:
            try:
                run_test(series, test)
            except TestError as e:
                echo_err(e)
                exit(1)

    except NonBinarySequenceError as e:
        echo_err(e)
        exit(1)


@main.command()
@argument("data", type=Path(exists=True))
@option("-d", "--dtype", type=dtype_choice, help=help_msg["dtype"], metavar="<dtype>")
@option("-t", "--test", type=test_choice, help=help_msg["test"], metavar="<test>")
def local_run(data, dtype, test):
    """Run randomness tests on DATA directly."""
    try:
        series = parse_data(data)
        echo_series(series)
    except (DataParsingError, NonBinarySequenceError) as e:
        echo_err(e)
        exit(1)

    try:
        if not test:
            for name, result, e in run_all_tests(series):
                if e:
                    echo_err(e)

        else:
            try:
                run_test(series, test)
            except TestError as e:
                echo_err(e)
                exit(1)

    except NonBinarySequenceError as e:
        echo_err(e)
        exit(1)


# TODO implement a non-write, no-with way to access results
@main.command()
@argument("store", autocompletion=get_stores, required=False, metavar="STORE")
@option("-o", "--outfile", type=Path())
def report(store, outfile):
    """Generate html report from test results in STORE."""
    if not outfile:
        echo("Please specify --outfile! Default behaviour is not implemented yet")
        exit(1)

    if not store:
        store = infer_store()

    try:
        with open_results(store) as results:
            for e in write_report(results, outfile):
                echo_err(e)

    except StoreNotFoundError as e:
        echo_err(e)
        exit(1)