using TaxCollectData.Library.Domain.Interfaces;

namespace TaxCollectData.Library.Infrastructure.Algorithms;

/// <summary>
/// Verhoeff algorithm implementation for error detection
/// </summary>
public class VerhoeffAlgorithm : IErrorDetectionAlgorithm
{
    private readonly int[,] _multiplicationTable = {
        {0, 1, 2, 3, 4, 5, 6, 7, 8, 9},
        {1, 2, 3, 4, 0, 6, 7, 8, 9, 5},
        {2, 3, 4, 0, 1, 7, 8, 9, 5, 6},
        {3, 4, 0, 1, 2, 8, 9, 5, 6, 7},
        {4, 0, 1, 2, 3, 9, 5, 6, 7, 8},
        {5, 9, 8, 7, 6, 0, 4, 3, 2, 1},
        {6, 5, 9, 8, 7, 1, 0, 4, 3, 2},
        {7, 6, 5, 9, 8, 2, 1, 0, 4, 3},
        {8, 7, 6, 5, 9, 3, 2, 1, 0, 4},
        {9, 8, 7, 6, 5, 4, 3, 2, 1, 0}
    };

    private readonly int[,] _permutationTable = {
        {0, 1, 2, 3, 4, 5, 6, 7, 8, 9},
        {1, 5, 7, 6, 2, 8, 3, 0, 9, 4},
        {5, 8, 0, 3, 7, 9, 6, 1, 4, 2},
        {8, 9, 1, 6, 0, 4, 3, 5, 2, 7},
        {9, 4, 5, 3, 1, 2, 6, 8, 7, 0},
        {4, 2, 8, 6, 5, 7, 3, 9, 0, 1},
        {2, 7, 9, 3, 8, 0, 6, 4, 1, 5},
        {7, 0, 4, 6, 9, 1, 3, 2, 5, 8}
    };

    private readonly int[] _inverseTable = { 0, 4, 3, 2, 1, 5, 6, 7, 8, 9 };

    public string GenerateCheckDigit(string number)
    {
        if (string.IsNullOrWhiteSpace(number))
        {
            throw new ArgumentException("Number cannot be null or empty", nameof(number));
        }

        var c = 0;
        var myArray = StringToReversedIntArray(number);

        for (var i = 0; i < myArray.Length; i++)
        {
            c = _multiplicationTable[c, _permutationTable[((i + 1) % 8), myArray[i]]];
        }

        return _inverseTable[c].ToString();
    }

    public bool ValidateCheckDigit(string number)
    {
        if (string.IsNullOrWhiteSpace(number))
        {
            return false;
        }

        var c = 0;
        var myArray = StringToReversedIntArray(number);

        for (var i = 0; i < myArray.Length; i++)
        {
            c = _multiplicationTable[c, _permutationTable[(i % 8), myArray[i]]];
        }

        return c == 0;
    }

    private static int[] StringToReversedIntArray(string number)
    {
        var myArray = new int[number.Length];

        for (var i = 0; i < number.Length; i++)
        {
            if (!char.IsDigit(number[i]))
            {
                throw new ArgumentException($"Invalid character in number: {number[i]}", nameof(number));
            }
            myArray[i] = int.Parse(number.Substring(i, 1));
        }

        Array.Reverse(myArray);
        return myArray;
    }
}

