namespace TaxCollectData.Library.Domain.ValueObjects;

/// <summary>
/// شناسه مشتری (MemoryId)
/// </summary>
public sealed class ClientId
{
    public string Value { get; }

    public ClientId(string value)
    {
        if (string.IsNullOrWhiteSpace(value))
        {
            throw new ArgumentException("ClientId cannot be null or empty", nameof(value));
        }

        Value = value;
    }

    public static implicit operator string(ClientId clientId) => clientId.Value;
    public static implicit operator ClientId(string value) => new(value);

    public override string ToString() => Value;

    public override bool Equals(object? obj)
    {
        return obj is ClientId other && Value == other.Value;
    }

    public override int GetHashCode() => Value.GetHashCode();
}

