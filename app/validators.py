
from pathlib import Path

from django.core.exceptions import ValidationError
from PIL import Image, UnidentifiedImageError


MAX_IMAGE_SIZE = 5 * 1024 * 1024

ALLOWED_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.webp'}
ALLOWED_FORMATS = {'JPEG', 'PNG', 'WEBP'}


def validate_image_file(file):
    if file.size > MAX_IMAGE_SIZE:
        raise ValidationError('Размер изображения не должен превышать 5 МБ.')

    filename = Path(file.name)
    suffix = filename.suffix.lower()

    if suffix not in ALLOWED_EXTENSIONS:
        raise ValidationError('Разрешены только JPG, JPEG, PNG и WEBP.')

    if len(filename.suffixes) > 1:
        raise ValidationError('Файлы с двойным расширением запрещены.')

    try:
        file.seek(0)

        with Image.open(file) as image:
            if image.format not in ALLOWED_FORMATS:
                raise ValidationError('Недопустимый формат изображения.')

            image.verify()

        file.seek(0)

    except (UnidentifiedImageError, OSError):
        raise ValidationError('Файл не является корректным изображением.')
