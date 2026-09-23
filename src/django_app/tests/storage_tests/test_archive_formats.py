from tables.services.storage_service.archive_formats import is_archive_name


def test_routing():
    assert is_archive_name("a.zip")
    assert is_archive_name("a.tar.gz")
    assert is_archive_name("a.TGZ")
    assert is_archive_name("a.tbz")
    assert is_archive_name("a.taz")
    assert not is_archive_name("a.txt")
    assert not is_archive_name("a.docx")
    assert not is_archive_name("a.jar")


def test_every_tar_alias_the_content_sniffing_path_accepted_is_still_routed():
    # the non-streaming upload detected archives by content, so these aliases used to
    # be extracted; extension routing has to name them explicitly or they regress
    for name in ("x.tar", "x.tgz", "x.taz", "x.tar.gz", "x.tar.bz2", "x.tbz", "x.tbz2", "x.tar.xz", "x.txz"):
        assert is_archive_name(name), name
