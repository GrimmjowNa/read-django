"""
Common checksum routines (used in multiple localflavor/ cases, for example).
"""

__all__ = ['luhn',]

LUHN_ODD_LOOKUP = (0, 2, 4, 6, 8, 1, 3, 5, 7, 9) # sum_of_digits(index * 2)

"""@author Nick.Na

    信用卡验证算法-luhn算法

        1、从卡号最后一位数字开始，逆向将奇数位(1、3、5等)相加。
        2、将偶数位数字相加，须先将数字乘以2，如果结果是两位数，将两个位上数字相加。然后将这些结果加入总和中。
        3、将奇数位总和加上偶数位总和，如果信用卡号码是合法的，结果应该可以被10整除。
"""
def luhn(candidate):
    """
    Checks a candidate number for validity according to the Luhn
    algorithm (used in validation of, for example, credit cards).
    Both numeric and string candidates are accepted.
    """
    if not isinstance(candidate, basestring):
        candidate = str(candidate)
    try:
        evens = sum([int(c) for c in candidate[-1::-2]])
        odds = sum([LUHN_ODD_LOOKUP[int(c)] for c in candidate[-2::-2]])
        return ((evens + odds) % 10 == 0)
    except ValueError:  # Raised if an int conversion fails
        return False
