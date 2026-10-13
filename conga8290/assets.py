"""Import only pinned shipped artifacts from a local XAPK; never extractall()."""
import hashlib
import io
import os
from pathlib import Path
import stat
import tempfile
import zipfile

from .packaged_oem_identity import APK_SHA256

ROOT = Path(__file__).resolve().parents[1]
EXPECTED = {
    'es.cecotec.forceclima.apk': APK_SHA256,
    'cloud-native/libthing_security.so': '7340fe7f3c0f999c5913b8a8d3effb603be3631bd1cea6455806178ffd18b38f',
    'cloud-native/libthing_security_algorithm.so': '401954bae1c402b3b4b4145ebd5b180bd90d0e18f02ff67b6c804e143512f903',
}


def owned_directory(path):
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    info = path.lstat()
    if (not stat.S_ISDIR(info.st_mode) or stat.S_IMODE(info.st_mode) != 0o700 or
            info.st_uid != os.getuid()):
        raise ValueError('private_directory_must_be_owned_mode_0700')


def member(archive, name, limit):
    if archive.namelist().count(name) != 1:
        raise ValueError('expected_xapk_member_missing_or_duplicate')
    info = archive.getinfo(name)
    if info.is_dir() or not 0 < info.file_size <= limit:
        raise ValueError('xapk_member_budget_exceeded')
    return archive.read(info)


def prepare_xapk(path, directory=None):
    directory = ROOT / 'artifacts' if directory is None else Path(directory)
    if not path.is_file() or path.stat().st_size > 512 * 1048576:
        raise ValueError('bounded_local_xapk_required')
    with zipfile.ZipFile(path) as archive:
        base = member(archive, 'es.cecotec.forceclima.apk', 128 * 1048576)
        split = member(archive, 'config.arm64_v8a.apk', 128 * 1048576)
    with zipfile.ZipFile(io.BytesIO(split)) as archive:
        payloads = {'es.cecotec.forceclima.apk': base}
        for name in ['libthing_security.so', 'libthing_security_algorithm.so']:
            payloads['cloud-native/' + name] = member(archive, 'lib/arm64-v8a/' + name, 4 * 1048576)
    for name, data in payloads.items():
        if hashlib.sha256(data).hexdigest() != EXPECTED[name]:
            raise ValueError('unsupported_cecotec_artifact')
    # Verify ALL artifacts before writing anything. Never replace existing files.
    for name in payloads:
        target = directory / name
        if target.exists() or target.is_symlink():
            info = target.lstat()
            if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or
                    stat.S_IMODE(info.st_mode) != 0o600 or
                    hashlib.sha256(target.read_bytes()).hexdigest() != EXPECTED[name]):
                raise ValueError('existing_artifact_not_compatible')
    owned_directory(directory)
    owned_directory(directory / 'cloud-native')
    for name, data in payloads.items():
        target = directory / name
        if target.exists():
            continue
        with tempfile.NamedTemporaryFile(prefix='.import-', dir=target.parent) as temporary:
            temporary.write(data)
            temporary.flush()
            os.fsync(temporary.fileno())
            os.link(temporary.name, target)  # Atomic creation; no overwrite.
    return True
