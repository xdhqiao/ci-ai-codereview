def get_user_account_name_map() -> dict[str, str]:
    """Return the account-to-display-name mapping supplied by the business layer."""
    return {
        "dahai": "大海",
        "xiaoming": "小明",
    }


def get_user_display_name(account: str) -> str:
    normalized = (account or "").strip()
    return get_user_account_name_map().get(normalized, normalized)
