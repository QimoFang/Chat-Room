"""Headless smoke test for UI.py: instantiate ChatApp, exercise core flow, exit."""
import tkinter as tk
import UI


def main():
    root = tk.Tk()
    app = UI.ChatApp(root)
    root.update_idletasks()
    root.update()

    # 1) sidebar has contacts
    assert app.sidebar.contacts, "no contacts loaded"
    print(f"contacts: {len(app.sidebar.contacts)}")

    # 2) open each conversation to make sure messages render
    for c in app.sidebar.contacts[:3]:
        app._open_conversation(c)
        root.update_idletasks()
        root.update()
        assert app._messages is not None
        print(f"opened {c.name}: msgs area y={app._messages._y}")

    # 3) test sending
    app._open_conversation(app.sidebar.contacts[0])
    app._send("Hello from smoke test")
    root.update_idletasks()
    root.update()
    print("send: ok")

    # 4) test empty state
    app._show_empty_state()
    root.update_idletasks()
    root.update()
    print("empty state: ok")

    root.destroy()
    print("ALL OK")


if __name__ == "__main__":
    main()
