"""Headshot storage: one square JPEG per player, kept in git so it survives Render redeploys."""
import io
import os

import github_sync
import store

DIR = os.path.join(store.DATA_DIR, 'headshots')


def path(slug):
    return os.path.join(DIR, f'{slug}.jpg')


def exists(slug):
    return os.path.exists(path(slug))


def save(slug, fileobj, push=True):
    """Center-crops to a square, 400px, JPEG. Returns True on success."""
    from PIL import Image, ImageOps
    img = ImageOps.exif_transpose(Image.open(fileobj)).convert('RGB')
    w, h = img.size
    s = min(w, h)
    top = max(0, int((h - s) * 0.2)) if h > w else (h - s) // 2   # portraits: bias toward the face
    left = (w - s) // 2
    img = img.crop((left, top, left + s, top + s)).resize((400, 400), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, 'JPEG', quality=85, optimize=True)
    os.makedirs(DIR, exist_ok=True)
    with open(path(slug), 'wb') as f:
        f.write(buf.getvalue())
    if push:
        github_sync.put_file(f'data/headshots/{slug}.jpg', buf.getvalue())
    return True


def delete(slug, push=True):
    if exists(slug):
        os.remove(path(slug))
        if push:
            github_sync.delete_file(f'data/headshots/{slug}.jpg')


def move(old, new, push=True):
    if exists(old) and old != new:
        data = open(path(old), 'rb').read()
        delete(old, push)
        os.makedirs(DIR, exist_ok=True)
        open(path(new), 'wb').write(data)
        if push:
            github_sync.put_file(f'data/headshots/{new}.jpg', data)
