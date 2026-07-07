from conftest import TEST_BUCKET, load_tool, seed

tool = load_tool("s3_bash_tool")


# =====================================================================
# ls
# =====================================================================


def test_ls_flat_shows_top_level_only(patched_storage, fake_client):
    seed(fake_client, "dir/a.txt", "x")
    seed(fake_client, "dir/sub/b.txt", "y")

    result = tool.main(command="ls dir")

    assert "a.txt" in result
    assert "sub/" in result
    assert "b.txt" not in result


def test_ls_recursive(patched_storage, fake_client):
    seed(fake_client, "dir/a.txt", "x")
    seed(fake_client, "dir/sub/b.txt", "y")

    result = tool.main(command="ls -R dir")

    assert "dir/a.txt" in result
    assert "dir/sub/b.txt" in result


def test_ls_long_shows_size(patched_storage, fake_client):
    seed(fake_client, "dir/a.txt", "hello")

    result = tool.main(command="ls -l dir")

    assert "5" in result


def test_ls_combined_short_flags(patched_storage, fake_client):
    seed(fake_client, "dir/a.txt", "hello")

    result = tool.main(command="ls -lR dir")

    assert "dir/a.txt" in result
    assert "5" in result


def test_ls_missing_path(patched_storage, fake_client):
    result = tool.main(command="ls nowhere")

    assert "No files or folders found" in result


def test_ls_glob_expansion(patched_storage, fake_client):
    seed(fake_client, "dir/a.txt", "x")
    seed(fake_client, "dir/b.log", "y")

    result = tool.main(command="ls dir/*.txt")

    assert "dir/a.txt" in result
    assert "dir/b.log" not in result


def test_glob_star_does_not_cross_directory_boundary(patched_storage, fake_client):
    seed(fake_client, "dir/a.txt", "x")
    seed(fake_client, "dir/sub/b.txt", "y")

    result = tool.main(command="ls dir/*.txt")

    assert "dir/a.txt" in result
    assert "dir/sub/b.txt" not in result


def test_glob_top_level_star_does_not_match_nested(patched_storage, fake_client):
    seed(fake_client, "a.txt", "x")
    seed(fake_client, "dir/b.txt", "y")

    result = tool.main(command="ls *.txt")

    assert "a.txt" in result
    assert "dir/b.txt" not in result


def test_glob_question_mark_does_not_match_slash(patched_storage, fake_client):
    seed(fake_client, "dir/file.txt", "x")
    seed(fake_client, "dirXfile.txt", "y")

    result = tool.main(command="ls dir?file.txt")

    assert "dirXfile.txt" in result
    assert "dir/file.txt" not in result


# =====================================================================
# cat
# =====================================================================


def test_cat_single_file(patched_storage, fake_client):
    seed(fake_client, "a.txt", "hello\nworld")

    result = tool.main(command="cat a.txt")

    assert result == "hello\nworld"


def test_cat_with_line_numbers(patched_storage, fake_client):
    seed(fake_client, "a.txt", "hello\nworld")

    result = tool.main(command="cat -n a.txt")

    assert "1\thello" in result
    assert "2\tworld" in result


def test_cat_multiple_files_have_headers(patched_storage, fake_client):
    seed(fake_client, "a.txt", "AAA")
    seed(fake_client, "b.txt", "BBB")

    result = tool.main(command="cat a.txt b.txt")

    assert "==> a.txt <==" in result
    assert "==> b.txt <==" in result
    assert "AAA" in result
    assert "BBB" in result


def test_cat_missing_file(patched_storage, fake_client):
    result = tool.main(command="cat missing.txt")

    assert "File not found" in result


def test_cat_glob_expansion(patched_storage, fake_client):
    seed(fake_client, "logs/a.log", "AAA")
    seed(fake_client, "logs/b.log", "BBB")

    result = tool.main(command="cat logs/*.log")

    assert "AAA" in result
    assert "BBB" in result


def test_cat_glob_no_match(patched_storage, fake_client):
    seed(fake_client, "a.txt", "x")

    result = tool.main(command="cat missing*.txt")

    assert "no matches for pattern" in result


def test_cat_folder_path_errors(patched_storage, fake_client):
    seed(fake_client, "dir/a.txt", "x")

    result = tool.main(command="cat dir/")

    assert "folder" in result.lower()


# =====================================================================
# head / tail
# =====================================================================


def test_head_default_ten_lines(patched_storage, fake_client):
    content = "\n".join(f"line{i}" for i in range(20))
    seed(fake_client, "a.txt", content)

    result = tool.main(command="head a.txt")

    assert "line0" in result
    assert "line9" in result
    assert "line10" not in result


def test_head_with_n_flag(patched_storage, fake_client):
    content = "\n".join(f"line{i}" for i in range(20))
    seed(fake_client, "a.txt", content)

    result = tool.main(command="head -n 3 a.txt")

    assert result == "line0\nline1\nline2"


def test_tail_with_n_flag(patched_storage, fake_client):
    content = "\n".join(f"line{i}" for i in range(20))
    seed(fake_client, "a.txt", content)

    result = tool.main(command="tail -n 2 a.txt")

    assert result == "line18\nline19"


def test_head_multiple_files_glob_errors(patched_storage, fake_client):
    seed(fake_client, "a.txt", "x")
    seed(fake_client, "b.txt", "y")

    result = tool.main(command="head *.txt")

    assert "single path" in result or "matched" in result


def test_head_invalid_n(patched_storage, fake_client):
    seed(fake_client, "a.txt", "x")

    result = tool.main(command="head -n abc a.txt")

    assert "integer" in result


# =====================================================================
# wc
# =====================================================================


def test_wc_default_shows_all_three(patched_storage, fake_client):
    seed(fake_client, "a.txt", "hello world\nfoo")

    result = tool.main(command="wc a.txt")

    parts = result.split()
    assert len(parts) == 4  # lines words bytes filename
    assert parts[-1] == "a.txt"


def test_wc_lines_only(patched_storage, fake_client):
    seed(fake_client, "a.txt", "a\nb\nc")

    result = tool.main(command="wc -l a.txt")

    parts = result.split()
    assert len(parts) == 2
    assert parts[0] == "2"


def test_wc_multiple_files_show_total(patched_storage, fake_client):
    seed(fake_client, "a.txt", "one two")
    seed(fake_client, "b.txt", "three")

    result = tool.main(command="wc -w a.txt b.txt")

    assert "total" in result


# =====================================================================
# grep
# =====================================================================


def test_grep_basic_match_no_line_numbers_by_default(patched_storage, fake_client):
    seed(fake_client, "a.txt", "hello\nworld")

    result = tool.main(command="grep hello a.txt")

    assert "a.txt: hello" in result
    assert "a.txt:1:" not in result


def test_grep_line_numbers_flag(patched_storage, fake_client):
    seed(fake_client, "a.txt", "hello\nworld\nhello again")

    result = tool.main(command="grep -n hello a.txt")

    assert "a.txt:1: hello" in result
    assert "a.txt:3: hello again" in result


def test_grep_ignore_case(patched_storage, fake_client):
    seed(fake_client, "a.txt", "Hello World")

    result = tool.main(command="grep -i hello a.txt")

    assert "Hello World" in result


def test_grep_files_with_matches(patched_storage, fake_client):
    seed(fake_client, "a.txt", "target")
    seed(fake_client, "b.txt", "nope")

    result = tool.main(command="grep -l target")

    assert result == "a.txt"


def test_grep_non_recursive_by_default(patched_storage, fake_client):
    seed(fake_client, "a.txt", "target")
    seed(fake_client, "dir/b.txt", "target")

    result = tool.main(command="grep target")

    assert "a.txt" in result
    assert "dir/b.txt" not in result


def test_grep_recursive_flag(patched_storage, fake_client):
    seed(fake_client, "a.txt", "target")
    seed(fake_client, "dir/b.txt", "target")

    result = tool.main(command="grep -r target")

    assert "a.txt" in result
    assert "dir/b.txt" in result


def test_grep_combined_flags(patched_storage, fake_client):
    seed(fake_client, "dir/a.txt", "Target here")

    result = tool.main(command="grep -rin target dir")

    assert "dir/a.txt:1: Target here" in result


def test_grep_quoted_pattern_with_pipe_is_not_rejected(patched_storage, fake_client):
    seed(fake_client, "a.txt", "abc\ndef\nxyz")

    result = tool.main(command='grep "(abc|def)" a.txt')

    assert "abc" in result
    assert "def" in result
    assert "xyz" not in result


def test_grep_invalid_regex(patched_storage, fake_client):
    result = tool.main(command="grep [unclosed a.txt")

    assert "Invalid regex" in result


# =====================================================================
# find
# =====================================================================


def test_find_lists_files_and_folders(patched_storage, fake_client):
    seed(fake_client, "dir/a.py", "x")
    seed(fake_client, "dir/sub/b.txt", "y")

    result = tool.main(command="find")

    assert "dir/a.py" in result
    assert "dir/sub/b.txt" in result
    assert "dir" in result
    assert "dir/sub" in result


def test_find_type_d_only(patched_storage, fake_client):
    seed(fake_client, "dir/a.py", "x")
    seed(fake_client, "dir/sub/b.txt", "y")

    result = tool.main(command="find -type d")

    assert "dir" in result
    assert "dir/sub" in result
    assert "dir/a.py" not in result


def test_find_name_pattern(patched_storage, fake_client):
    seed(fake_client, "dir/a.py", "x")
    seed(fake_client, "dir/b.txt", "y")

    result = tool.main(command="find dir -name *.py")

    assert "dir/a.py" in result
    assert "dir/b.txt" not in result


def test_find_invalid_type(patched_storage, fake_client):
    seed(fake_client, "a.py", "x")

    result = tool.main(command="find -type x")

    assert "must be 'f' or 'd'" in result


# =====================================================================
# mkdir
# =====================================================================


def test_mkdir_creates_folder(patched_storage, fake_client):
    result = tool.main(command="mkdir newdir")

    assert "Folder created: newdir." in result
    assert any(k.endswith("newdir/.keep") for k in fake_client.objects)


def test_mkdir_already_exists(patched_storage, fake_client):
    seed(fake_client, "existing/file.txt", "x")

    result = tool.main(command="mkdir existing")

    assert "already exists" in result


def test_mkdir_without_p_missing_parent_errors(patched_storage, fake_client):
    result = tool.main(command="mkdir a/b/c")

    assert "parent folder" in result
    assert "does not exist" in result


def test_mkdir_with_p_creates_regardless(patched_storage, fake_client):
    result = tool.main(command="mkdir -p a/b/c")

    assert "Folder created: a/b/c." in result


# =====================================================================
# rm
# =====================================================================


def test_rm_deletes_file(patched_storage, fake_client):
    seed(fake_client, "a.txt", "x")

    result = tool.main(command="rm a.txt")

    assert "Deleted a.txt." in result
    assert "a.txt" not in fake_client.objects


def test_rm_folder_without_r_errors(patched_storage, fake_client):
    seed(fake_client, "dir/a.txt", "x")

    result = tool.main(command="rm dir")

    assert "pass -r" in result
    assert "dir/a.txt" in fake_client.objects


def test_rm_folder_with_r_deletes(patched_storage, fake_client):
    seed(fake_client, "dir/a.txt", "x")
    seed(fake_client, "dir/b.txt", "y")

    result = tool.main(command="rm -r dir")

    assert "Deleted folder dir" in result
    assert "dir/a.txt" not in fake_client.objects
    assert "dir/b.txt" not in fake_client.objects


def test_rm_root_refused_empty(patched_storage, fake_client):
    seed(fake_client, "a.txt", "x")

    result = tool.main(command="rm ''")

    assert "refusing to remove root" in result
    assert "a.txt" in fake_client.objects


def test_rm_root_refused_slash(patched_storage, fake_client):
    seed(fake_client, "a.txt", "x")

    result = tool.main(command="rm /")

    assert "refusing to remove root" in result


def test_rm_root_refused_dot(patched_storage, fake_client):
    seed(fake_client, "a.txt", "x")

    result = tool.main(command="rm .")

    assert "refusing to remove root" in result


def test_rm_not_found_without_f_reports_error(patched_storage, fake_client):
    result = tool.main(command="rm missing.txt")

    assert "cannot remove" in result


def test_rm_not_found_with_f_is_suppressed(patched_storage, fake_client):
    result = tool.main(command="rm -f missing.txt")

    assert "ignored" in result
    assert "cannot remove" not in result


def test_rm_multiple_paths(patched_storage, fake_client):
    seed(fake_client, "a.txt", "x")
    seed(fake_client, "b.txt", "y")

    result = tool.main(command="rm a.txt b.txt")

    assert "a.txt" not in fake_client.objects
    assert "b.txt" not in fake_client.objects
    assert "Deleted a.txt." in result
    assert "Deleted b.txt." in result


def test_rm_glob_no_match_without_f(patched_storage, fake_client):
    result = tool.main(command="rm missing*.txt")

    assert "no matches for pattern" in result


def test_rm_glob_no_match_with_f_is_silent(patched_storage, fake_client):
    result = tool.main(command="rm -f missing*.txt")

    assert result == "Nothing to remove."


# =====================================================================
# mv / cp
# =====================================================================


def test_mv_file(patched_storage, fake_client):
    seed(fake_client, "a.txt", "hello")

    result = tool.main(command="mv a.txt b.txt")

    assert "Moved a.txt to b.txt." in result
    assert "a.txt" not in fake_client.objects
    assert fake_client.objects["b.txt"]["Body"] == b"hello"


def test_mv_folder_errors(patched_storage, fake_client):
    seed(fake_client, "dir/a.txt", "x")

    result = tool.main(command="mv dir otherdir")

    assert "folder" in result.lower()
    assert "cp -r" in result
    assert "dir/a.txt" in fake_client.objects


def test_cp_file(patched_storage, fake_client):
    seed(fake_client, "a.txt", "hello")

    result = tool.main(command="cp a.txt b.txt")

    assert "Copied a.txt to b.txt." in result
    assert fake_client.objects["b.txt"]["Body"] == b"hello"
    assert "a.txt" in fake_client.objects


def test_cp_folder_without_r_errors(patched_storage, fake_client):
    seed(fake_client, "srcdir/a.txt", "x")

    result = tool.main(command="cp srcdir dstdir")

    assert "use cp -r" in result


def test_cp_folder_with_r_copies_all_files(patched_storage, fake_client):
    seed(fake_client, "srcdir/a.txt", "AAA")
    seed(fake_client, "srcdir/sub/b.txt", "BBB")

    result = tool.main(command="cp -r srcdir dstdir")

    assert "2 file(s)" in result
    assert fake_client.objects["dstdir/a.txt"]["Body"] == b"AAA"
    assert fake_client.objects["dstdir/sub/b.txt"]["Body"] == b"BBB"
    assert "srcdir/a.txt" in fake_client.objects  # copy keeps source


def test_cp_glob_multiple_sources_into_folder(patched_storage, fake_client):
    seed(fake_client, "logs/a.log", "AAA")
    seed(fake_client, "logs/b.log", "BBB")

    result = tool.main(command="cp logs/*.log archive/")

    assert "2 file(s)" in result
    assert fake_client.objects["archive/a.log"]["Body"] == b"AAA"
    assert fake_client.objects["archive/b.log"]["Body"] == b"BBB"


# =====================================================================
# touch
# =====================================================================


def test_touch_creates_empty_file(patched_storage, fake_client):
    result = tool.main(command="touch newfile.txt")

    assert "Created empty file: newfile.txt." in result
    assert fake_client.objects["newfile.txt"]["Body"] == b""


def test_touch_existing_file_is_noop(patched_storage, fake_client):
    seed(fake_client, "a.txt", "hello")

    result = tool.main(command="touch a.txt")

    assert "already exists" in result
    assert fake_client.objects["a.txt"]["Body"] == b"hello"


def test_touch_on_folder_errors(patched_storage, fake_client):
    seed(fake_client, "dir/a.txt", "x")

    result = tool.main(command="touch dir")

    assert "is a folder" in result


# =====================================================================
# stat
# =====================================================================


def test_stat_file(patched_storage, fake_client):
    seed(fake_client, "a.txt", "hello")

    result = tool.main(command="stat a.txt")

    assert "type: file" in result
    assert "size: 5 bytes" in result


def test_stat_folder(patched_storage, fake_client):
    seed(fake_client, "dir/a.txt", "x")

    result = tool.main(command="stat dir")

    assert "type: folder" in result
    assert "entries: 1" in result


def test_stat_missing(patched_storage, fake_client):
    result = tool.main(command="stat missing.txt")

    assert "File not found" in result


# =====================================================================
# du
# =====================================================================


def test_du_grand_total(patched_storage, fake_client):
    seed(fake_client, "a.txt", "hello")  # 5 bytes
    seed(fake_client, "dir/b.txt", "abc")  # 3 bytes

    result = tool.main(command="du")

    assert "8" in result
    assert "(total)" in result


def test_du_summary_only(patched_storage, fake_client):
    seed(fake_client, "a.txt", "hello")
    seed(fake_client, "dir/b.txt", "abc")

    result = tool.main(command="du -s")

    assert "8" in result
    assert "(total)" not in result


def test_du_missing_path_errors(patched_storage, fake_client):
    result = tool.main(command="du missing")

    assert "No such file or folder" in result


def test_du_empty_existing_folder_is_zero(patched_storage, fake_client):
    fake_client.put_object(Bucket=TEST_BUCKET, Key="emptydir/.keep", Body=b"")

    result = tool.main(command="du emptydir")

    assert "0" in result


# =====================================================================
# diff
# =====================================================================


def test_diff_shows_differences(patched_storage, fake_client):
    seed(fake_client, "a.txt", "line1\nline2\n")
    seed(fake_client, "b.txt", "line1\nlineX\n")

    result = tool.main(command="diff a.txt b.txt")

    assert "-line2" in result
    assert "+lineX" in result


def test_diff_identical_files(patched_storage, fake_client):
    seed(fake_client, "a.txt", "same content")
    seed(fake_client, "b.txt", "same content")

    result = tool.main(command="diff a.txt b.txt")

    assert "identical" in result


# =====================================================================
# echo + redirection
# =====================================================================


def test_echo_without_redirect(patched_storage, fake_client):
    result = tool.main(command="echo hello world")

    assert result == "hello world"


def test_echo_redirect_creates_file(patched_storage, fake_client):
    result = tool.main(command="echo hi > out.txt")

    assert "Wrote" in result
    assert fake_client.objects["out.txt"]["Body"] == b"hi\n"


def test_echo_redirect_overwrites_existing_file(patched_storage, fake_client):
    seed(fake_client, "out.txt", "old content here")

    tool.main(command="echo new > out.txt")

    assert fake_client.objects["out.txt"]["Body"] == b"new\n"


def test_echo_redirect_append(patched_storage, fake_client):
    seed(fake_client, "out.txt", "abc")

    result = tool.main(command="echo def >> out.txt")

    assert "Appended" in result
    assert fake_client.objects["out.txt"]["Body"] == b"abcdef\n"


def test_echo_redirect_append_twice_lands_as_separate_lines(
    patched_storage, fake_client
):
    tool.main(command="echo a >> out.txt")
    tool.main(command="echo b >> out.txt")

    assert fake_client.objects["out.txt"]["Body"] == b"a\nb\n"


def test_echo_without_redirect_has_no_trailing_newline(patched_storage, fake_client):
    result = tool.main(command="echo hi")

    assert result == "hi"


def test_cat_redirect_writes_rendered_output(patched_storage, fake_client):
    seed(fake_client, "a.txt", "hello")

    result = tool.main(command="cat -n a.txt > out.txt")

    assert "Wrote" in result
    assert b"1\thello" in fake_client.objects["out.txt"]["Body"]


def test_redirect_not_supported_for_other_commands(patched_storage, fake_client):
    seed(fake_client, "dir/a.txt", "x")

    result = tool.main(command="ls dir > out.txt")

    assert "not supported" in result
    assert "out.txt" not in fake_client.objects


# =====================================================================
# test / [
# =====================================================================


def test_test_dash_e_true(patched_storage, fake_client):
    seed(fake_client, "a.txt", "x")

    result = tool.main(command="test -e a.txt")

    assert result == "true"


def test_test_dash_e_false(patched_storage, fake_client):
    result = tool.main(command="test -e missing.txt")

    assert result == "false"


def test_bracket_form(patched_storage, fake_client):
    seed(fake_client, "a.txt", "x")

    result = tool.main(command="[ -e a.txt ]")

    assert result == "true"


def test_bracket_missing_closing_bracket_errors(patched_storage, fake_client):
    result = tool.main(command="[ -e a.txt")

    assert "missing closing" in result


# =====================================================================
# rejected syntax
# =====================================================================


def test_pipe_rejected(patched_storage, fake_client):
    result = tool.main(command="cat a.txt | grep foo")

    assert "Pipes" in result


def test_and_chaining_rejected(patched_storage, fake_client):
    result = tool.main(command="cat a.txt && echo hi")

    assert "chaining" in result.lower()


def test_or_chaining_rejected(patched_storage, fake_client):
    result = tool.main(command="cat a.txt || echo hi")

    assert "chaining" in result.lower()


def test_semicolon_rejected(patched_storage, fake_client):
    result = tool.main(command="cat a.txt; echo hi")

    assert "chaining" in result.lower()


def test_variable_rejected(patched_storage, fake_client):
    result = tool.main(command="echo $HOME")

    assert "Variables" in result


def test_backtick_subshell_rejected(patched_storage, fake_client):
    result = tool.main(command="echo `whoami`")

    assert "Subshells" in result or "backticks" in result


def test_dollar_paren_subshell_rejected(patched_storage, fake_client):
    result = tool.main(command="echo $(whoami)")

    assert "Subshells" in result


def test_input_redirect_rejected(patched_storage, fake_client):
    result = tool.main(command="cat < a.txt")

    assert "Input redirection" in result


def test_quoted_dollar_is_not_rejected(patched_storage, fake_client):
    result = tool.main(command="echo '$HOME'")

    assert result == "$HOME"


# =====================================================================
# parsing edge cases
# =====================================================================


def test_empty_command_returns_usage(patched_storage, fake_client):
    result = tool.main(command="")

    assert "no command given" in result


def test_unknown_command(patched_storage, fake_client):
    result = tool.main(command="foobar something")

    assert "Unknown command 'foobar'" in result
    assert "s3_grep_tool" in result


def test_quoted_args_with_spaces(patched_storage, fake_client):
    seed(fake_client, "my file.txt", "hello there")

    result = tool.main(command='cat "my file.txt"')

    assert result == "hello there"


def test_output_is_capped(patched_storage, fake_client, monkeypatch):
    monkeypatch.setattr(tool, "_MAX_OUTPUT_CHARS", 20)
    seed(fake_client, "a.txt", "x" * 200)

    result = tool.main(command="cat a.txt")

    assert "output truncated" in result
