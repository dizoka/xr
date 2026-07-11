from aiogram.fsm.state import State, StatesGroup


class UserSearchStates(StatesGroup):
    query = State()
