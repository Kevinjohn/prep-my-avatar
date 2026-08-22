"""Exact, bounded perceptual-hash matching for corpus deduplication."""

from PIL import Image


DEFAULT_MAX_DISTANCE = 8


def dhash(image: Image.Image) -> int:
    """Return a 64-bit horizontal-gradient dHash for a Pillow image."""
    with image.convert('L') as gray, gray.resize((9, 8), Image.Resampling.LANCZOS) as resized:
        pixels = list(resized.get_flattened_data())
    bits = 0
    for row in range(8):
        for column in range(8):
            left = pixels[row * 9 + column]
            right = pixels[row * 9 + column + 1]
            bits = (bits << 1) | (left > right)
    return bits


def hamming(left: int, right: int) -> int:
    return (left ^ right).bit_count()


class DHashIndex:
    """Exact radius-eight candidate index for 64-bit perceptual hashes.

    Nine disjoint bands guarantee that hashes differing in at most eight bits
    share at least one complete band. Lookup therefore avoids a full corpus
    scan without accepting approximate false negatives inside the radius.
    """

    _WIDTHS = (8, 7, 7, 7, 7, 7, 7, 7, 7)

    def __init__(self, pairs=()):
        self._pairs = []
        self._buckets = {}
        for payload, value in pairs:
            self.add(payload, value)

    @classmethod
    def _bands(cls, value):
        offset = 0
        for index, width in enumerate(cls._WIDTHS):
            yield index, (value >> offset) & ((1 << width) - 1)
            offset += width

    def add(self, payload, value):
        position = len(self._pairs)
        self._pairs.append((payload, value))
        for key in self._bands(value):
            self._buckets.setdefault(key, set()).add(position)

    def nearest_within(self, value):
        """Closest indexed hash within `DEFAULT_MAX_DISTANCE` bits, or (None, None).

        The radius is fixed, not a knob. Eight is the largest distance the nine
        bands above can answer EXACTLY (the pigeonhole argument in the class
        docstring), so a caller-chosen larger radius would quietly return false
        negatives, and a smaller one is a filter the caller can apply to the
        distance this already returns. It used to be a parameter guarded by two
        never-raised ValueErrors; no caller has ever passed it.
        """
        candidates = set()
        for key in self._bands(value):
            candidates.update(self._buckets.get(key, ()))
        best = None
        best_distance = DEFAULT_MAX_DISTANCE + 1
        for position in sorted(candidates):
            payload, candidate = self._pairs[position]
            distance = hamming(value, candidate)
            if distance < best_distance:
                best, best_distance = (payload, candidate), distance
        return ((best, best_distance)
                if best is not None and best_distance <= DEFAULT_MAX_DISTANCE
                else (None, None))

    def __bool__(self):
        return bool(self._pairs)
