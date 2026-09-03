"""Jarvis Control Plane — unified Event/State/Command layer.

All subsystems publish events, expose state, and accept commands
through this layer. CLI, WebUI, Telegram, Waybar, and Voice
all consume the same interface.
"""
