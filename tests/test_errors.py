from app.errors import format_validation_errors


def test_formats_validation_error_without_leaking_input() -> None:
    message = format_validation_errors(
        [
            {
                "type": "string_too_short",
                "loc": ("body", "model"),
                "msg": "String should have at least 1 character",
                "input": "secret-value",
                "ctx": {"min_length": 1},
            }
        ]
    )
    assert message == "模型名称至少需要 1 个字符"
    assert "secret-value" not in message
