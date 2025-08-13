import uuid
def new_order_uid() -> str:
    return str(uuid.uuid4())