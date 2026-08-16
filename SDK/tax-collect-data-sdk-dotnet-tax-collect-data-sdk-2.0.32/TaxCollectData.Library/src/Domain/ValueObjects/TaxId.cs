namespace TaxCollectData.Library.Domain.ValueObjects;

/// <summary>
/// شناسه مالیاتی فاکتور
/// </summary>
public sealed class TaxId
{
    public string Value { get; }

    public TaxId(string value)
    {
        if (string.IsNullOrWhiteSpace(value))
        {
            throw new ArgumentException("TaxId cannot be null or empty", nameof(value));
        }

        Value = value;
    }

    public static implicit operator string(TaxId taxId) => taxId.Value;
    public static implicit operator TaxId(string value) => new(value);

    public override string ToString() => Value;

    public override bool Equals(object? obj)
    {
        return obj is TaxId other && Value == other.Value;
    }

    public override int GetHashCode() => Value.GetHashCode();
}

