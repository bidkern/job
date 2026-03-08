from app.services.distance import distance_from_base_zip


def test_distance_from_base_zip_known_zip():
    value = distance_from_base_zip("44224", "44114")
    assert value is not None
    assert value > 0


def test_distance_unknown_zip():
    assert distance_from_base_zip("44224", "00000") is None
