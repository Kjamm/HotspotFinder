"""Managed local installations; licensed archives are supplied by the user."""
import stat
import tarfile
import zipfile
from pathlib import Path, PurePosixPath

from . import engines

MAX_EXPANDED = 20 * 1024**3


def safe_extract(archive, destination, check=lambda: None):
    """Extract ordinary files only, never links/devices or paths outside destination."""
    archive, destination = Path(archive), Path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    total, seen = 0, set()

    def copy(src, dst):
        while True:
            check()
            chunk = src.read(1024 * 1024)
            if not chunk:
                break
            dst.write(chunk)

    def target(name, size):
        nonlocal total
        name = name.replace('\\', '/')
        parts = PurePosixPath(name)
        if parts.is_absolute() or '..' in parts.parts or ':' in name or '\x00' in name:
            raise ValueError('안전하지 않은 압축 파일 경로입니다.')
        path = destination.joinpath(*parts.parts).resolve()
        if destination.resolve() not in path.parents:
            raise ValueError('설치 폴더 밖의 압축 경로입니다.')
        if path in seen:
            raise ValueError('압축 파일에 중복된 파일 경로가 있습니다.')
        seen.add(path)
        total += size
        if total > MAX_EXPANDED or len(seen) > 200000:
            raise ValueError('압축 해제 크기 또는 파일 수 제한을 초과했습니다.')
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    if zipfile.is_zipfile(archive):
        with zipfile.ZipFile(archive) as z:
            for member in z.infolist():
                if member.is_dir():
                    continue
                mode = member.external_attr >> 16
                if stat.S_ISLNK(mode):
                    continue
                path = target(member.filename, member.file_size)
                with z.open(member) as src, path.open('wb') as dst:
                    copy(src, dst)
                path.chmod(0o700 if mode & 0o111 else 0o600)
    elif tarfile.is_tarfile(archive):
        with tarfile.open(archive) as t:
            for member in t:
                if member.isdir() or member.issym() or member.islnk():
                    continue
                if not member.isfile():
                    raise ValueError('특수 파일을 포함한 압축 파일은 지원하지 않습니다.')
                path = target(member.name, member.size)
                with t.extractfile(member) as src, path.open('wb') as dst:
                    copy(src, dst)
                path.chmod(0o700 if member.mode & 0o111 else 0o600)
    else:
        raise ValueError('ZIP 또는 TAR/TAR.GZ 배포 파일을 선택하세요.')


def binary(path):
    with path.open('rb') as f:
        magic = f.read(4)
    return magic in (b'\x7fELF', b'\xcf\xfa\xed\xfe', b'\xce\xfa\xed\xfe', b'\xfe\xed\xfa\xcf', b'\xca\xfe\xba\xbe', b'\xca\xfe\xba\xbf')


def install_archive(engine, archive, destination, check=lambda: None):
    if engine not in ('foldx', 'flex_ddg'):
        raise ValueError('이 엔진은 배포 파일 설치를 지원하지 않습니다.')
    safe_extract(archive, destination, check)
    candidates = []
    for path in Path(destination).rglob('*'):
        check()
        if not path.is_file():
            continue
        name = path.name.lower()
        if (engine == 'foldx' and name.startswith('foldx')) or (engine == 'flex_ddg' and name.startswith('rosetta_scripts')):
            if binary(path):
                candidates.append(path)
    if len(candidates) != 1:
        raise ValueError('해당 플랫폼의 실행 파일 하나가 필요합니다. 소스 전용 또는 여러 플랫폼이 섞인 패키지는 고급 설정에서 연결하세요. 발견: ' + ', '.join(p.name for p in candidates))
    executable = candidates[0]
    executable.chmod(0o700)
    data_dir = executable.parent
    if engine == 'flex_ddg':
        databases = [p for p in Path(destination).rglob('database') if p.is_dir() and (p / 'scoring').is_dir()]
        if len(databases) != 1:
            raise ValueError('Rosetta database/scoring 디렉터리가 포함된 배포 패키지가 필요합니다.')
        data_dir = databases[0]
    else:
        rotabases = list(Path(destination).rglob('rotabase.txt'))
        if len(rotabases) == 1:
            data_dir = rotabases[0].parent
    config = {'id': engine, 'executable': str(executable.resolve()), 'data_dir': str(data_dir.resolve()), 'image': '', 'version': 'archive sha256:' + engines.sha(archive)[:16], 'status': 'needs_validation', 'validation': None}
    return config
