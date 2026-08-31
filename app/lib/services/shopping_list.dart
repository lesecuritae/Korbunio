import 'package:flutter/services.dart';

import '../api/models.dart';

/// Where a collected set of offers can be sent.
enum ShoppingListRoute {
  /// The KitchenOwl list behind the KorbKlar server, which stores a proper
  /// article plus a note.
  server,

  /// The clipboard, one line per offer. The fallback where no list is
  /// configured, so collecting is never a dead end.
  clipboard,
}

/// Formats collected offers as text.
class ShoppingListText {
  const ShoppingListText();

  /// One offer as a single line: product, pack, retailer and price.
  ///
  /// Only values the offer actually carries are included, matching how the
  /// server builds its note.
  static String lineFor(Offer offer) {
    final price = offer.effectivePriceText.isNotEmpty
        ? offer.effectivePriceText
        : offer.regularPriceText;
    final parts = [
      offer.product,
      if (offer.pack.isNotEmpty) offer.pack,
      if (offer.retailerText.isNotEmpty) offer.retailerText,
      if (price.isNotEmpty) price,
    ];
    return parts.join(' · ');
  }

  static String textFor(List<Offer> offers) => offers.map(lineFor).join('\n');

  /// Puts the collection on the clipboard.
  Future<void> copy(List<Offer> offers) async {
    if (offers.isEmpty) return;
    await Clipboard.setData(ClipboardData(text: textFor(offers)));
  }
}
