from unittest.mock import patch

from bootstrap import lifespans
from infrastructure.naive.chunkers.strategies.token_chunker import load_gpt2_tokenizer
from infrastructure.naive.chunkers.strategies import token_chunker
from infrastructure.token_estimation import _WARM_UP_MODELS, warm_up_token_counter


def test_gpt2_tokenizer_is_loaded_once_and_reused():
    load_gpt2_tokenizer.cache_clear()
    try:
        with (
            patch.object(token_chunker.settings, "TOKENIZER_PATH", "/tokenizers/gpt2.tkz"),
            patch.object(token_chunker.Tokenizer, "from_file") as from_file,
        ):
            first = load_gpt2_tokenizer()
            second = load_gpt2_tokenizer()
    finally:
        load_gpt2_tokenizer.cache_clear()
    from_file.assert_called_once_with("/tokenizers/gpt2.tkz")
    assert first is second


def test_warm_up_token_counter_counts_each_warm_up_model():
    with (
        patch("infrastructure.token_estimation.count_tokens") as count,
        patch("infrastructure.token_estimation.price_per_token") as price,
    ):
        warm_up_token_counter()
    assert [call.args[0] for call in count.call_args_list] == list(_WARM_UP_MODELS)
    assert [call.args[0] for call in price.call_args_list] == list(_WARM_UP_MODELS)


def test_failing_tokenizer_preload_does_not_abort_startup():
    with patch.object(lifespans, "load_gpt2_tokenizer", side_effect=OSError("offline")):
        lifespans.preload_token_chunker_tokenizer()


def test_failing_token_counter_warm_up_does_not_abort_startup():
    with patch.object(lifespans, "warm_up_token_counter", side_effect=RuntimeError("boom")):
        lifespans.preload_token_counter()


def test_failing_graphrag_preload_does_not_abort_startup():
    with (
        patch.object(lifespans, "is_graphrag_available", return_value=True),
        patch.object(lifespans, "import_module", side_effect=ImportError("boom")),
    ):
        lifespans.preload_graphrag_modules()


def test_graphrag_modules_are_not_imported_without_avx2():
    with (
        patch.object(lifespans, "is_graphrag_available", return_value=False),
        patch.object(lifespans, "import_module") as import_module,
    ):
        lifespans.preload_graphrag_modules()
    import_module.assert_not_called()


def test_every_graphrag_module_is_imported_when_available():
    with (
        patch.object(lifespans, "is_graphrag_available", return_value=True),
        patch.object(lifespans, "import_module") as import_module,
    ):
        lifespans.preload_graphrag_modules()
    assert [call.args[0] for call in import_module.call_args_list] == list(
        lifespans._GRAPHRAG_MODULES
    )
