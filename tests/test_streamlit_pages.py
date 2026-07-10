from __future__ import annotations

from streamlit.testing.v1 import AppTest


def test_dashboard_loads_without_firestore_secrets():
    app = AppTest.from_file("streamlit_dashboard.py").run(timeout=30)

    assert not app.exception
    assert app.title[0].value == "Shannon Demon Dashboard"
    assert app.info


def test_manual_page_loads_with_uat_and_blank_credentials():
    app = AppTest.from_file("pages/Manual.py").run(timeout=30)

    assert not app.exception
    assert app.title[0].value == "🧪 Manual Test Lab"
    assert len(app.tabs) == 6
    assert app.sidebar.selectbox[0].value == "Test (UAT)"
    assert app.sidebar.text_input[0].value == ""
    assert app.sidebar.text_input[1].value == ""
    assert app.sidebar.text_input[2].value == ""


def test_clear_credentials_callback_clears_all_secret_widgets():
    app = AppTest.from_file("pages/Manual.py").run(timeout=30)
    app.sidebar.text_input[0].set_value("account")
    app.sidebar.text_input[1].set_value("key")
    app.sidebar.text_input[2].set_value("secret")
    app.run(timeout=30)

    app.sidebar.button[0].click().run(timeout=30)

    assert not app.exception
    assert [field.value for field in app.sidebar.text_input[:3]] == ["", "", ""]
