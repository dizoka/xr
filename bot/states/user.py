from aiogram.fsm.state import State, StatesGroup


class UserSearchStates(StatesGroup):
    query = State()


class UserOrderStates(StatesGroup):
    quantity = State()
    variant = State()
    cart = State()
