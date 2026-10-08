// Mirrors the API default (PASSWORD_MIN_LENGTH in apps/api/config.py) so users
// see the rule before submitting. The API is the authority: if an operator
// raises the minimum, the server's error message is shown instead.
export const PASSWORD_MIN_LENGTH = 8;
