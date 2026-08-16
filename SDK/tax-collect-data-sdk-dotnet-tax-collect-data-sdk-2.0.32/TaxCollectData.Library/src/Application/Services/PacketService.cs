using System.Text;
using TaxCollectData.Library.Application.DTOs;
using TaxCollectData.Library.Application.Interfaces;
using TaxCollectData.Library.Domain.ValueObjects;
using TaxCollectData.Library.Infrastructure.Crypto;
using TaxCollectData.Library.Infrastructure.Serialization;

namespace TaxCollectData.Library.Application.Services;

/// <summary>
/// Service for creating invoice packets
/// </summary>
public class PacketService : IPacketService
{
    private readonly ClientId _clientId;
    private readonly ISignatory _signatory;
    private readonly IEncryptor _encryptor;
    private readonly IJsonSerializer _serializer;

    public PacketService(
        ClientId clientId,
        ISignatory signatory,
        IEncryptor encryptor,
        IJsonSerializer serializer)
    {
        _clientId = clientId ?? throw new ArgumentNullException(nameof(clientId));
        _signatory = signatory ?? throw new ArgumentNullException(nameof(signatory));
        _encryptor = encryptor ?? throw new ArgumentNullException(nameof(encryptor));
        _serializer = serializer ?? throw new ArgumentNullException(nameof(serializer));
    }

    public PacketDto CreateInvoicePacket(InvoiceDto invoice)
    {
        if (invoice == null)
        {
            throw new ArgumentNullException(nameof(invoice));
        }

        var serializedInvoice = _serializer.Serialize(invoice);
        var signedInvoice = _signatory.Sign(serializedInvoice);
        var encryptedInvoice = _encryptor.Encrypt(signedInvoice);

        return new PacketDto
        {
            Payload = encryptedInvoice,
            Header = CreateHeader()
        };
    }

    private PacketHeaderDto CreateHeader()
    {
        return new PacketHeaderDto
        {
            RequestTraceId = Guid.NewGuid().ToString(),
            FiscalId = _clientId.Value
        };
    }
}

