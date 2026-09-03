/// How an offer becomes a KitchenOwl article.
///
/// KitchenOwl keeps a household's staples as articles with icons: "Brot",
/// "Wasser", "Butter". A leaflet calls the same thing "JA! Weizenbrötchen
/// 6 Stück". Filing the offer under the household's own article keeps the
/// icon and lets next week's differently worded offer land on the same
/// entry; the leaflet wording moves into the note.
///
/// Pure Dart, so it can be tested without a device or a KitchenOwl.
library;

import '../api/models.dart';

/// Below this an existing article says too little to be worth matching:
/// "Ei" would swallow half a catalogue.
const _minMatchLength = 4;

/// A household staple is named in a word or three. Anything longer in the
/// catalogue is an offer headline, most likely one an earlier version filed
/// there, and matching against it would keep every later offer for the
/// same product away from the real article.
const _maxArticleWords = 3;

const _trailingWords = {
  'aus', 'mit', 'ohne', 'in', 'im', 'von', 'vom', 'der', 'die', 'das', //
  'und', 'oder', 'je', 'pro', 'à', 'a', 'zum', 'zur', 'nach', 'verschiedene',
  'versch', 'sowie', 'auch', 'z', 'b',
};

const _unit = r'g|kg|mg|ml|cl|l|stk|stück|st|x|er';
final _packWord = RegExp(
  '^([0-9]+([.,][0-9]+)?\\s*($_unit)?|$_unit|packung|beutel|dose|schale)[.,]?\$',
  caseSensitive: false,
);

final _letter = RegExp(r'\p{L}', unicode: true);

const maxArticleLength = 200;
const maxNoteLength = 300;

String _clean(String value) => value.replaceAll(RegExp(r'\s+'), ' ').trim();

String _truncate(String value, int limit) {
  final text = _clean(value);
  if (text.length <= limit) return text;
  return '${text.substring(0, limit - 1).trimRight()}…';
}

/// Whether a word reads as a brand or marketing line rather than a product.
///
/// Leaflets shout their private labels: "GUT&GÜNSTIG", "JA!", "REWE BESTE
/// WAHL". Three letters keep "H-Milch" and unit letters out of this; a
/// shouted word with an exclamation mark is a label however short.
bool _isBrandToken(String token) {
  final letters = _letter.allMatches(token).length;
  final shouted = token == token.toUpperCase() && token != token.toLowerCase();
  return shouted && (letters >= 3 || (letters >= 2 && token.endsWith('!')));
}

/// Returns the staple an offer is about, without the leaflet wording.
///
/// "GUT&GÜNSTIG Weizenbrötchen / Schrippen" is a household's "Weizenbrötchen".
/// The full offer wording is not lost: it goes into the note.
String shortenOfferName(String product) {
  var text = _clean(product);
  if (text.isEmpty) return '';
  // An alternative spelling after a slash describes the same product.
  final head = text.split('/').first.trim();
  if (head.length >= _minMatchLength) text = head;
  var words = text.split(' ').where((word) => word.isNotEmpty).toList();
  // "Rinderhackfleisch aus der Region" is bought as Rinderhackfleisch; what
  // follows such a word qualifies the offer, not the product.
  for (var index = 1; index < words.length; index++) {
    final word = words[index].toLowerCase().replaceAll(
      RegExp(r'^[,.]+|[,.]+$'),
      '',
    );
    if (_trailingWords.contains(word)) {
      words = words.sublist(0, index);
      break;
    }
  }
  var kept = words.where((word) => !_isBrandToken(word)).toList();
  if (kept.isEmpty) kept = words;
  // A pack size belongs in the note, not in the article name.
  while (kept.length > 1 && _packWord.hasMatch(kept.last)) {
    kept.removeLast();
  }
  // German puts the head noun last, so when trimming, the tail is the part
  // that says what the product is.
  final tail = kept.length > _maxArticleWords
      ? kept.sublist(kept.length - _maxArticleWords)
      : kept;
  return tail.join(' ');
}

/// Reduces a name to comparable words.
List<String> _fold(String value) => _clean(value)
    .toLowerCase()
    .replaceAll(RegExp(r'[^0-9a-zäöüß]+'), ' ')
    .trim()
    .split(' ')
    .where((word) => word.isNotEmpty)
    .toList();

/// Whether a catalogue entry is a leaflet headline instead of a staple.
bool _isOfferHeadline(String name) {
  final words = _clean(name).split(' ');
  return words.length > _maxArticleWords ||
      (words.length > 1 && words.any(_isBrandToken));
}

/// Whether the article's words appear in the offer, compounds included.
///
/// German puts the head noun last, so an article named "Brötchen" is what
/// "Weizenbrötchen" is. Only the final word may match as a suffix; matching
/// the front would turn "Buttermilch" into butter.
bool _containsSequence(List<String> words, List<String> parts) {
  if (parts.isEmpty) return false;
  final last = parts.length - 1;
  for (var start = 0; start + last < words.length; start++) {
    var matches = true;
    for (var offset = 0; offset < last; offset++) {
      if (words[start + offset] != parts[offset]) {
        matches = false;
        break;
      }
    }
    if (!matches) continue;
    final candidate = words[start + last];
    if (candidate == parts[last] || candidate.endsWith(parts[last])) {
      return true;
    }
  }
  return false;
}

/// Returns the household's own article name for this offer, or '' if none.
///
/// An offer is called "GUT&GÜNSTIG Weizenbrötchen / Schrippen" while the
/// household keeps a plain "Brötchen". Matching on whole words lets the offer
/// land on the article that already exists instead of creating a near
/// duplicate, and the longest match wins so "Bio Butter" beats "Butter".
String matchExistingItem(String product, Iterable<String> catalogue) {
  final words = _fold(product);
  var best = '';
  var bestLength = 0;
  for (final name in catalogue) {
    if (_isOfferHeadline(name)) continue;
    final parts = _fold(name);
    final folded = parts.join(' ');
    if (folded.length < _minMatchLength || folded.length <= bestLength) {
      continue;
    }
    if (_containsSequence(words, parts)) {
      best = name;
      bestLength = folded.length;
    }
  }
  return best;
}

/// The article an offer is filed under: the household's own article when
/// one matches, otherwise the shortened offer name.
String articleFor(Offer offer, Iterable<String> catalogue) {
  final matched = matchExistingItem(offer.product, catalogue);
  if (matched.isNotEmpty) return matched;
  final short = _truncate(shortenOfferName(offer.product), maxArticleLength);
  if (short.isNotEmpty) return short;
  final retailer = _clean(offer.retailerText);
  return retailer.isEmpty ? 'Angebot' : 'Angebot $retailer';
}

/// The note shown underneath the article: offer name, price, validity.
///
/// The offer name only appears when the article is called something else,
/// otherwise it would stand there twice. Pack size and unit price are left
/// out on purpose: the note is read in the shop, where what matters is
/// which offer this is, what it costs and until when.
String noteFor(Offer offer, String article) {
  final price = offer.effectivePriceText.isNotEmpty
      ? offer.effectivePriceText
      : offer.regularPriceText;
  final product = _clean(offer.product);
  final parts = [
    if (product != _clean(article)) product,
    if (price.isNotEmpty) price,
    if (offer.validity.isNotEmpty) offer.validity,
  ];
  return _truncate(parts.join(' · '), maxNoteLength);
}

/// KitchenOwl categories carry a name and nothing else, so the icon can only
/// be an emoji in front of it. The colours follow the shops' logos, so a list
/// sorted by category reads like a row of storefronts.
const _retailerIcons = {
  'aldi nord': '🔵',
  'aldi süd': '🔵',
  'aldi': '🔵',
  'lidl': '🟡',
  'rewe': '🔴',
  'edeka': '🟡',
  'marktkauf': '🟠',
  'kaufland': '🔴',
  'penny': '🔴',
  'netto marken-discount': '🟡',
  'netto schwarz': '⚫',
  'globus': '🟢',
  'hol’ab!': '🟢',
  "hol'ab!": '🟢',
  'rossmann': '🔴',
  'müller': '🟠',
  'dm': '🔵',
  'combi': '🟢',
  'famila nordwest': '🔵',
  'famila': '🔵',
};

/// The category an offer's retailer is filed under, e.g. "🔴 REWE".
///
/// Empty when the offer names no retailer. A merged row that stands for
/// several shops keeps its first retailer, which is the one the offer key
/// already refers to.
String retailerCategory(String retailer) {
  final name = _clean(retailer);
  if (name.isEmpty) return '';
  final icon = _retailerIcons[name.toLowerCase()] ?? '🛒';
  return '$icon $name';
}
