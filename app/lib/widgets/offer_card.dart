import 'package:flutter/material.dart';

import '../api/models.dart';
import '../theme.dart';

/// One offer row, laid out for a phone.
///
/// The web table has seven columns; on a narrow screen the same information is
/// stacked instead. Every value is rendered as the server formatted it.
class OfferCard extends StatelessWidget {
  const OfferCard({
    super.key,
    required this.offer,
    required this.imageUrl,
    required this.imageHeaders,
    required this.showRetailer,
    required this.filedIn,
    required this.sending,
    required this.onAddToList,
    required this.onOpenSource,
    this.onLocalList = false,
    this.onAddToKitchenOwl,
    this.onRemoveFromKitchenOwl,
  });

  final Offer offer;
  final String? imageUrl;

  /// Passed with the image request; the proxy is gated like every other
  /// route, so an unauthenticated load would only yield a placeholder.
  final Map<String, String> imageHeaders;

  /// Hidden when the list is already filtered to a single retailer, matching
  /// the web interface's `single-retailer` rule.
  final bool showRetailer;

  /// The KitchenOwl list this offer was already filed in, or null while it
  /// has not been.
  final String? filedIn;
  final bool sending;

  /// Toggles the offer on the app's local list: adds it, or removes it when
  /// [onLocalList] says it is already there. Null hides that button, which
  /// is what "only KitchenOwl" in the settings means.
  final VoidCallback? onAddToList;

  /// Whether the offer is already on the local list.
  final bool onLocalList;
  final VoidCallback onOpenSource;

  /// Files the offer in KitchenOwl. Null while no KitchenOwl is connected.
  final VoidCallback? onAddToKitchenOwl;

  /// Takes a filed offer off the KitchenOwl list again. Null where the app
  /// cannot do that, in which case a filed offer stays as it is and is
  /// removed by checking it off in KitchenOwl.
  final VoidCallback? onRemoveFromKitchenOwl;

  Color _stateColor(String state, KorbColors colors) =>
      state == 'best' ? colors.good : colors.text;

  @override
  Widget build(BuildContext context) {
    final colors = context.colors;
    return Container(
      decoration: BoxDecoration(
        color: colors.panel,
        borderRadius: BorderRadius.circular(14),
        border: Border.all(
          color: filedIn != null ? colors.good : colors.line,
          width: filedIn != null ? 2 : 1,
        ),
      ),
      padding: const EdgeInsets.all(12),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              _Thumb(url: imageUrl, headers: imageHeaders),
              const SizedBox(width: 12),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    if (showRetailer || offer.isMerged)
                      Text(
                        offer.retailerText,
                        style: TextStyle(
                          fontWeight: FontWeight.w700,
                          fontSize: 13,
                          color: colors.accent,
                        ),
                      ),
                    if (offer.isMerged)
                      Text(
                        'gleiches Angebot',
                        style: TextStyle(color: colors.muted, fontSize: 11),
                      ),
                    InkWell(
                      onTap: offer.sourceUrl.isEmpty ? null : onOpenSource,
                      child: Text(
                        offer.product,
                        style: const TextStyle(
                          fontWeight: FontWeight.w600,
                          fontSize: 15,
                          height: 1.25,
                        ),
                      ),
                    ),
                    if (offer.category.isNotEmpty)
                      Text(
                        offer.category,
                        style: TextStyle(color: colors.muted, fontSize: 12),
                      ),
                    if (offer.description.isNotEmpty)
                      Padding(
                        padding: const EdgeInsets.only(top: 2),
                        child: Text(
                          offer.description,
                          style: TextStyle(color: colors.muted, fontSize: 13),
                        ),
                      ),
                  ],
                ),
              ),
              const SizedBox(width: 8),
              ConstrainedBox(
                constraints: const BoxConstraints(maxWidth: 110),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.end,
                  children: [
                    Text(
                      offer.effectivePriceText,
                      style: TextStyle(
                        fontSize: 19,
                        fontWeight: FontWeight.w800,
                        color: offer.hasSaving
                            ? colors.good
                            : _stateColor(
                                offer.selectedComparisonState,
                                colors,
                              ),
                      ),
                    ),
                    if (offer.hasSaving &&
                        offer.regularPriceText != offer.effectivePriceText)
                      Text(
                        offer.regularPriceText,
                        style: TextStyle(
                          color: colors.muted,
                          fontSize: 13,
                          decoration: TextDecoration.lineThrough,
                        ),
                      ),
                    if (offer.selectedComparisonState == 'best')
                      Text(
                        'Günstigster Vergleichspreis',
                        textAlign: TextAlign.end,
                        style: TextStyle(
                          color: colors.good,
                          fontSize: 10,
                          fontWeight: FontWeight.w600,
                        ),
                      ),
                  ],
                ),
              ),
            ],
          ),
          const SizedBox(height: 8),
          Wrap(
            spacing: 10,
            runSpacing: 2,
            children: [
              if (offer.pack.isNotEmpty) _Meta(text: offer.pack),
              if (offer.unitPrice.isNotEmpty) _Meta(text: offer.unitPrice),
              if (offer.validity.isNotEmpty) _Meta(text: offer.validity),
            ],
          ),
          if (offer.loyaltyBenefit.isNotEmpty || offer.hasSaving)
            Padding(
              padding: const EdgeInsets.only(top: 6),
              child: Text(
                [
                  if (offer.loyaltyBenefit.isNotEmpty) offer.loyaltyBenefit,
                  if (offer.hasSaving) 'spart ${offer.loyaltySavingsText}',
                ].join(' · '),
                style: TextStyle(
                  color: colors.good,
                  fontSize: 13,
                  fontWeight: FontWeight.w600,
                ),
              ),
            ),
          if (offer.regularComparison.isNotEmpty ||
              offer.selectedComparison.isNotEmpty)
            Padding(
              padding: const EdgeInsets.only(top: 4),
              child: Text(
                offer.selectedComparison.isNotEmpty
                    ? offer.selectedComparison
                    : offer.regularComparison,
                style: TextStyle(color: colors.muted, fontSize: 12),
              ),
            ),
          const SizedBox(height: 6),
          Wrap(
            alignment: WrapAlignment.end,
            crossAxisAlignment: WrapCrossAlignment.center,
            children: [
              if (onAddToList != null)
                TextButton.icon(
                  onPressed: sending ? null : onAddToList,
                  icon: Icon(
                    onLocalList
                        ? Icons.remove_shopping_cart_outlined
                        : Icons.add_shopping_cart,
                    size: 18,
                  ),
                  label: Text(
                    onLocalList ? 'Von Liste entfernen' : 'Zur Einkaufsliste',
                  ),
                  style: TextButton.styleFrom(
                    foregroundColor: colors.accent,
                    disabledForegroundColor: colors.muted,
                    visualDensity: VisualDensity.compact,
                  ),
                ),
              if (onAddToKitchenOwl != null)
                TextButton.icon(
                  onPressed: sending
                      ? null
                      : filedIn != null
                      ? onRemoveFromKitchenOwl
                      : onAddToKitchenOwl,
                  icon: sending
                      ? const SizedBox(
                          height: 16,
                          width: 16,
                          child: CircularProgressIndicator(strokeWidth: 2),
                        )
                      : Icon(
                          filedIn == null
                              ? Icons.playlist_add
                              : onRemoveFromKitchenOwl != null
                              ? Icons.playlist_remove
                              : Icons.check,
                          size: 18,
                        ),
                  label: Text(
                    filedIn == null
                        ? 'Auf KitchenOwl'
                        : onRemoveFromKitchenOwl != null
                        ? 'Aus KitchenOwl entfernen'
                        : 'in $filedIn',
                  ),
                  style: TextButton.styleFrom(
                    foregroundColor: filedIn != null
                        ? colors.good
                        : colors.accent,
                    disabledForegroundColor: filedIn != null
                        ? colors.good
                        : colors.muted,
                    visualDensity: VisualDensity.compact,
                  ),
                ),
            ],
          ),
        ],
      ),
    );
  }
}

class _Meta extends StatelessWidget {
  const _Meta({required this.text});

  final String text;

  @override
  Widget build(BuildContext context) =>
      Text(text, style: TextStyle(color: context.colors.muted, fontSize: 13));
}

class _Thumb extends StatelessWidget {
  const _Thumb({required this.url, required this.headers});

  final String? url;
  final Map<String, String> headers;

  @override
  Widget build(BuildContext context) {
    final colors = context.colors;
    return ClipRRect(
      borderRadius: BorderRadius.circular(8),
      child: Container(
        width: 60,
        height: 60,
        // Product photos usually come on a white background, so a real image
        // keeps the white plate the web view uses. An empty slot follows the
        // theme instead, which would otherwise glare in dark mode.
        color: url == null ? colors.bg : Colors.white,
        child: url == null
            ? Icon(Icons.image_not_supported_outlined, color: colors.muted)
            : Image.network(
                url!,
                headers: headers,
                fit: BoxFit.contain,
                errorBuilder: (_, _, _) => Icon(
                  Icons.image_not_supported_outlined,
                  color: colors.line,
                ),
              ),
      ),
    );
  }
}
