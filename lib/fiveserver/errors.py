"""
Various exception classes
"""


class PacketServerError(Exception):
    def __init__(self, msg):
        Exception.__init__(self,msg)


class NetworkError(PacketServerError):
    """
    Generic network error
    """

class UnknownUserError(PacketServerError):
    """
    Server does not recognize this user
    """

class NoLobbyConnectionError(PacketServerError):
    """
    User does not have a lobby connection
    """

class UserAlreadyLoggedInError(PacketServerError):
    """
    This user is already logged in
    """

class ProfileNotFoundError(PacketServerError):
    """
    Profile not found
    """

class ConfigurationError(PacketServerError):
    """
    An error in server configuration
    """
