using TaxCollectData.Library.Application.DTOs;

namespace TaxCollectData.Library.Application.Interfaces;

/// <summary>
/// Service for creating invoice packets
/// </summary>
public interface IPacketService
{
    /// <summary>
    /// Creates an invoice packet from an invoice DTO
    /// </summary>
    PacketDto CreateInvoicePacket(InvoiceDto invoice);
}

