import subprocess

from core.versioning import Repo


def init(tmp_path):
    for a in (["init", "-q"], ["config", "user.email", "t@t"], ["config", "user.name", "t"]):
        subprocess.check_call(["git", *a], cwd=tmp_path)
    (tmp_path / "port").mkdir(); (tmp_path / "port/app.py").write_text("v1\n")
    subprocess.check_call(["git", "add", "."], cwd=tmp_path)
    subprocess.check_call(["git", "commit", "-qm", "base"], cwd=tmp_path)
    return Repo(tmp_path)


def test_rollback_restores_files_and_logs_numbers(tmp_path):
    r = init(tmp_path)
    (tmp_path / "port/app.py").write_text("v2\n")
    prop = r.propose(2)
    r.rollback(prop, 2, 0.79, ["HO-117", "HO-203"])
    assert (tmp_path / "port/app.py").read_text() == "v1\n"
    log = subprocess.check_output(["git", "log", "--format=%s"], cwd=tmp_path, text=True)
    assert "revert(port): v2 rolled back 0.79, regressions [HO-117, HO-203]" in log


def test_adopt_keeps_files(tmp_path):
    r = init(tmp_path)
    (tmp_path / "port/app.py").write_text("v2\n")
    r.propose(2); r.adopt(2, 0.81, 0.68)
    assert (tmp_path / "port/app.py").read_text() == "v2\n"
    assert "feat(port): v2 adopted 0.81 (+0.13), 0 regressions" in subprocess.check_output(["git", "log", "--format=%s"], cwd=tmp_path, text=True)


def test_rollback_with_dirty_tree_and_new_file(tmp_path):
    r = init(tmp_path)
    (tmp_path / "notes.txt").write_text("base\n")
    subprocess.check_call(["git", "add", "notes.txt"], cwd=tmp_path)
    subprocess.check_call(["git", "commit", "-qm", "notes"], cwd=tmp_path)
    (tmp_path / "port/app.py").write_text("bad\n")
    (tmp_path / "port/extra.py").write_text("new\n")
    prop = r.propose(2)
    (tmp_path / "notes.txt").write_text("dirty, not ours\n")
    r.rollback(prop, 2, 0.1, [])
    assert (tmp_path / "port/app.py").read_text() == "v1\n" and not (tmp_path / "port/extra.py").exists()
    assert (tmp_path / "notes.txt").read_text() == "dirty, not ours\n"
