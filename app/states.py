"""FSM states for generation flow."""

from aiogram.fsm.state import State, StatesGroup


class GenerationStates(StatesGroup):
    """States for the music generation wizard."""
    choosing_mode = State()         # Pick: idea / lyrics
    choosing_gender = State()       # Pick: male / female
    choosing_style = State()        # Pick style/genre
    entering_prompt = State()       # Type text description or lyrics
    entering_custom_style = State() # Type custom style
    generating = State()            # Waiting for Suno API
