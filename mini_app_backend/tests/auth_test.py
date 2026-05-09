import json
import time
from urllib.parse import urlencode
import pytest
from mini_app_backend.auth import validate_init_data, InitDataError, _compute_telegram_hash
from mini_app_backend.schemas import AuthContext, TelegramUser

def generate_init_data(bot_token: str, user_data: dict, auth_date: int = None, **kwargs) -> str:
    if auth_date is None:
        auth_date = int(time.time())

    data = {
        "auth_date": str(auth_date),
        "user": json.dumps(user_data),
        **kwargs
    }

    # Replicate _build_data_check_string logic
    pairs = [f"{k}={v}" for k, v in sorted(data.items())]
    data_check_string = "\n".join(pairs)

    hash_value = _compute_telegram_hash(bot_token, data_check_string)
    data["hash"] = hash_value

    # We use parse_qsl in _parse_init_data which handles urlencoded strings
    return urlencode(data)

@pytest.fixture
def bot_token():
    return "123456789:ABCdefGHIjklMNOpqrSTUvwxYZ"

@pytest.fixture
def user_data():
    return {
        "id": 12345,
        "first_name": "Test",
        "last_name": "User",
        "username": "testuser",
        "language_code": "en",
        "is_premium": True
    }

def test_validate_init_data_success(bot_token, user_data):
    init_data = generate_init_data(bot_token, user_data)
    max_age = 3600

    result = validate_init_data(init_data, bot_token, max_age)

    assert isinstance(result, AuthContext)
    assert result.user.id == user_data["id"]
    assert result.user.username == user_data["username"]
    assert result.raw_init_data == init_data

def test_validate_init_data_no_bot_token():
    with pytest.raises(InitDataError, match="BOT_TOKEN is required"):
        validate_init_data("data", "", 3600)

def test_validate_init_data_empty_data(bot_token):
    with pytest.raises(InitDataError, match="initData is missing"):
        validate_init_data("", bot_token, 3600)

def test_validate_init_data_missing_hash(bot_token):
    init_data = "auth_date=123&user={}"
    with pytest.raises(InitDataError, match="initData hash is missing"):
        validate_init_data(init_data, bot_token, 3600)

def test_validate_init_data_signature_mismatch(bot_token, user_data):
    init_data = generate_init_data(bot_token, user_data)
    # Tamper with data
    tampered_data = init_data.replace("testuser", "otheruser")

    with pytest.raises(InitDataError, match="initData signature mismatch"):
        validate_init_data(tampered_data, bot_token, 3600)

def test_validate_init_data_missing_auth_date(bot_token, user_data):
    data = {
        "user": json.dumps(user_data),
        "something": "else"
    }
    pairs = [f"{k}={v}" for k, v in sorted(data.items())]
    data_check_string = "\n".join(pairs)
    hash_value = _compute_telegram_hash(bot_token, data_check_string)
    data["hash"] = hash_value
    init_data = urlencode(data)

    with pytest.raises(InitDataError, match="auth_date is missing"):
        validate_init_data(init_data, bot_token, 3600)

def test_validate_init_data_invalid_auth_date(bot_token, user_data):
    data = {
        "auth_date": "not-a-number",
        "user": json.dumps(user_data),
    }
    pairs = [f"{k}={v}" for k, v in sorted(data.items())]
    data_check_string = "\n".join(pairs)
    hash_value = _compute_telegram_hash(bot_token, data_check_string)
    data["hash"] = hash_value
    init_data = urlencode(data)

    with pytest.raises(InitDataError, match="auth_date must be an integer"):
        validate_init_data(init_data, bot_token, 3600)

def test_validate_init_data_expired(bot_token, user_data):
    old_date = int(time.time()) - 4000
    init_data = generate_init_data(bot_token, user_data, auth_date=old_date)

    with pytest.raises(InitDataError, match="initData is expired"):
        validate_init_data(init_data, bot_token, 3600)

def test_validate_init_data_future(bot_token, user_data):
    future_date = int(time.time()) + 120
    init_data = generate_init_data(bot_token, user_data, auth_date=future_date)

    with pytest.raises(InitDataError, match="auth_date is invalid \(in the future\)"):
        validate_init_data(init_data, bot_token, 3600)

def test_validate_init_data_missing_user(bot_token):
    data = {
        "auth_date": str(int(time.time())),
        "foo": "bar"
    }
    pairs = [f"{k}={v}" for k, v in sorted(data.items())]
    data_check_string = "\n".join(pairs)
    hash_value = _compute_telegram_hash(bot_token, data_check_string)
    data["hash"] = hash_value
    init_data = urlencode(data)

    with pytest.raises(InitDataError, match="user payload is missing"):
        validate_init_data(init_data, bot_token, 3600)

def test_validate_init_data_invalid_user_json(bot_token):
    data = {
        "auth_date": str(int(time.time())),
        "user": "{invalid-json"
    }
    pairs = [f"{k}={v}" for k, v in sorted(data.items())]
    data_check_string = "\n".join(pairs)
    hash_value = _compute_telegram_hash(bot_token, data_check_string)
    data["hash"] = hash_value
    init_data = urlencode(data)

    with pytest.raises(InitDataError, match="user payload is invalid JSON"):
        validate_init_data(init_data, bot_token, 3600)

def test_validate_init_data_invalid_user_id(bot_token):
    data = {
        "auth_date": str(int(time.time())),
        "user": json.dumps({"username": "test"}) # Missing id
    }
    pairs = [f"{k}={v}" for k, v in sorted(data.items())]
    data_check_string = "\n".join(pairs)
    hash_value = _compute_telegram_hash(bot_token, data_check_string)
    data["hash"] = hash_value
    init_data = urlencode(data)

    with pytest.raises(InitDataError, match="user payload is invalid"):
        validate_init_data(init_data, bot_token, 3600)
