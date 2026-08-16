using TaxCollectData.Library.Application.DTOs;
using TaxCollectData.Library.Application.Interfaces;
using TaxCollectData.Library.Infrastructure.ExternalApi;

namespace TaxCollectData.Library.Application.Services;

/// <summary>
/// Service for invoice operations
/// </summary>
public class InvoiceService : IInvoiceService
{
    private readonly ITaxApiClient _taxApiClient;
    private readonly IPacketService _packetService;

    public InvoiceService(ITaxApiClient taxApiClient, IPacketService packetService)
    {
        _taxApiClient = taxApiClient ?? throw new ArgumentNullException(nameof(taxApiClient));
        _packetService = packetService ?? throw new ArgumentNullException(nameof(packetService));
    }

    public async Task<List<InvoiceResponseDto>> SendInvoicesAsync(List<InvoiceDto> invoices, CancellationToken cancellationToken = default)
    {
        if (invoices == null || invoices.Count == 0)
        {
            throw new ArgumentException("Invoices list cannot be null or empty", nameof(invoices));
        }

        var invoicePackets = invoices.Select(invoice => new
        {
            TaxId = invoice.Header.taxid,
            Packet = _packetService.CreateInvoicePacket(invoice)
        }).ToList();

        var packets = invoicePackets.Select(x => x.Packet).ToList();
        var response = await _taxApiClient.SendInvoicesAsync(packets, cancellationToken).ConfigureAwait(false);

        var taxIdMap = invoicePackets.ToDictionary(
            x => x.Packet.Header.RequestTraceId,
            x => x.TaxId);

        return response.Result.Select(r => new InvoiceResponseDto(
            r.Data,
            r.Uid,
            r.ReferenceNumber,
            taxIdMap[r.Uid])).ToList();
    }

    public async Task<List<InvoiceStatusDto>> GetInvoiceStatusAsync(List<string> taxIds, CancellationToken cancellationToken = default)
    {
        if (taxIds == null || taxIds.Count == 0)
        {
            throw new ArgumentException("TaxIds list cannot be null or empty", nameof(taxIds));
        }

        var response = await _taxApiClient.InquiryInvoiceStatusAsync(taxIds, cancellationToken).ConfigureAwait(false);
        
        return response.Select(r => new InvoiceStatusDto(
            r.TaxId,
            r.InvoiceStatus,
            r.Article6Status,
            r.Error)).ToList();
    }
}

