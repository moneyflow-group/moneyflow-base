class DeprecatedException(Exception):  # design-checker skip
    pass


class BaseException(Exception):
    message = ""

    def __init__(self, message="", status_code=400, *args, **kwargs):
        # TODO: Add better handling, so structlog catches the kwargs
        arguments = ", ".join([f"{k}: {v}" for k, v in kwargs.items()])
        self.message = f"{message}" + (f" [{arguments}]" if kwargs != {} else "")
        super().__init__(message, *args)
        self.http_status_code = status_code

    def http_error_text(self):
        return self.message


class ExternalAPIException(BaseException):
    pass


class InvalidCRN(BaseException):
    pass


class InvalidLocale(BaseException):
    pass


class EventlogException(BaseException):
    pass


class DuplicateEvent(EventlogException):
    pass


class MFValidationError(BaseException):
    pass
