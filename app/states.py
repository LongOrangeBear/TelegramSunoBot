"""FSM states for generation flow."""

from aiogram.fsm.state import State, StatesGroup


class GenerationStates(StatesGroup):
    """States for the music generation wizard."""
    choosing_mode = State()         # Pick: idea / lyrics / greeting
    choosing_gender = State()       # Pick: male / female
    choosing_style = State()        # Pick style/genre
    entering_prompt = State()       # Type text description or lyrics
    entering_custom_style = State() # Type custom style
    generating = State()            # Waiting for Suno API

    # Greeting wizard states
    greeting_recipient = State()    # Pick: кому (маме, папе, ...)
    greeting_name = State()         # Enter name / full name
    greeting_occasion = State()     # Pick: occasion (ДР, 23 февраля, ...)
    greeting_mood = State()         # Pick: serious / funny / mix
    greeting_details = State()      # Enter facts/details about the person

    # Stories wizard states
    stories_vibe = State()          # Pick: vibe/role (босс, на чиле, ...)
    stories_mood = State()          # Pick: mood (дерзко, мило, ...)
    stories_context = State()       # Enter context (what are you doing today)
    stories_name = State()          # Enter name/nickname (optional)
