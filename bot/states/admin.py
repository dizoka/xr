from aiogram.fsm.state import State, StatesGroup


class AddCategoryStates(StatesGroup):
    emoji = State()
    name = State()


class EditCategoryStates(StatesGroup):
    value = State()


class AddProductStates(StatesGroup):
    name = State()
    brand = State()
    price = State()
    description = State()
    photo = State()


class EditProductStates(StatesGroup):
    value = State()


class EditSettingStates(StatesGroup):
    value = State()


class StaffProductEditStates(StatesGroup):
    value = State()
