import logging

logger = logging.getLogger("Validation")

def validate_request(data, required_fields):
    """
    Validate if all required fields are present in the input data.
    :param data: The input data to validate (expected to be a dictionary).
    :param required_fields: A list of required field names.
    :return: True if all required fields are present and valid, False otherwise.
    """
    if not isinstance(data, dict):
        logger.error(f"Validation failed: Expected dict but got {type(data)}")
        return False

    missing_fields = [field for field in required_fields if field not in data or not data[field]]
    if missing_fields:
        logger.warning(f"Validation failed: Missing or invalid fields: {missing_fields}")
        return False

    logger.debug(f"Validation passed for required fields: {required_fields}")
    return True


def validate_number(value, min_value=None, max_value=None):
    """
    Validate if a value is a number within an optional range.
    :param value: The value to validate.
    :param min_value: Minimum allowable value (inclusive).
    :param max_value: Maximum allowable value (inclusive).
    :return: True if the value is valid, False otherwise.
    """
    try:
        num = float(value)
        if min_value is not None and num < min_value:
            logger.warning(f"Validation failed: {value} is less than minimum allowed value {min_value}")
            return False
        if max_value is not None and num > max_value:
            logger.warning(f"Validation failed: {value} is greater than maximum allowed value {max_value}")
            return False
        logger.debug(f"Validation passed for number: {value}")
        return True
    except (ValueError, TypeError):
        logger.error(f"Validation failed: {value} is not a valid number.")
        return False


def validate_string(value, min_length=1, max_length=None):
    """
    Validate if a value is a string within an optional length range.
    :param value: The value to validate.
    :param min_length: Minimum allowable length of the string.
    :param max_length: Maximum allowable length of the string.
    :return: True if the value is valid, False otherwise.
    """
    if not isinstance(value, str):
        logger.error(f"Validation failed: Expected string but got {type(value)}")
        return False
    if len(value) < min_length:
        logger.warning(f"Validation failed: String length {len(value)} is less than {min_length}")
        return False
    if max_length is not None and len(value) > max_length:
        logger.warning(f"Validation failed: String length {len(value)} exceeds {max_length}")
        return False
    logger.debug(f"Validation passed for string: {value}")
    return True


def validate_choice(value, choices):
    """
    Validate if a value is within a set of allowed choices.
    :param value: The value to validate.
    :param choices: A list or set of allowed values.
    :return: True if the value is valid, False otherwise.
    """
    if value not in choices:
        logger.warning(f"Validation failed: {value} is not in allowed choices {choices}")
        return False
    logger.debug(f"Validation passed for choice: {value}")
    return True
