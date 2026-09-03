/// Typed views over the KorbKlar REST responses.
///
/// Field names mirror `presentation.offer_for_response` and
/// `service.SupermarketEngine.page` on the server. The app never recomputes a
/// price: every value shown comes from the comparison engine.
library;

String _str(Object? value) => value is String ? value : '';

double? _num(Object? value) {
  if (value is num) return value.toDouble();
  if (value is String) return double.tryParse(value);
  return null;
}

int _int(Object? value) {
  if (value is num) return value.toInt();
  if (value is String) return int.tryParse(value) ?? 0;
  return 0;
}

Map<String, int> _counts(Object? value) {
  if (value is! Map) return const {};
  final result = <String, int>{};
  value.forEach((key, item) {
    if (key is String) result[key] = _int(item);
  });
  return result;
}

/// One comparable offer as rendered in a result row.
class Offer {
  Offer({
    required this.retailer,
    required this.retailers,
    required this.retailerLabel,
    required this.category,
    required this.product,
    required this.description,
    required this.regularPrice,
    required this.regularPriceText,
    required this.regularComparison,
    required this.regularComparisonState,
    required this.checkoutPriceText,
    required this.effectivePrice,
    required this.effectivePriceText,
    required this.selectedComparison,
    required this.selectedComparisonState,
    required this.loyaltySavings,
    required this.loyaltySavingsText,
    required this.loyaltyBenefit,
    required this.deposit,
    required this.depositText,
    required this.depositNote,
    required this.pack,
    required this.unitPrice,
    required this.selectedUnitPrice,
    required this.validity,
    required this.imageUrl,
    required this.sourceUrl,
  });

  factory Offer.fromJson(Map<String, dynamic> json) => Offer(
    retailer: _str(json['retailer']),
    retailers: (json['retailers'] as List? ?? [])
        .map(_str)
        .where((item) => item.isNotEmpty)
        .toList(),
    retailerLabel: _str(json['retailer_label']),
    category: _str(json['category']),
    product: _str(json['product']),
    description: _str(json['description']),
    regularPrice: _num(json['regular_price']),
    regularPriceText: _str(json['regular_price_text']),
    regularComparison: _str(json['regular_comparison']),
    regularComparisonState: _str(json['regular_comparison_state']),
    checkoutPriceText: _str(json['checkout_price_text']),
    effectivePrice: _num(json['effective_price']),
    effectivePriceText: _str(json['effective_price_text']),
    selectedComparison: _str(json['selected_comparison']),
    selectedComparisonState: _str(json['selected_comparison_state']),
    loyaltySavings: _num(json['loyalty_savings']) ?? 0,
    loyaltySavingsText: _str(json['loyalty_savings_text']),
    loyaltyBenefit: _str(json['loyalty_benefit']),
    deposit: _num(json['deposit']),
    depositText: _str(json['deposit_text']),
    depositNote: _str(json['deposit_note']),
    pack: _str(json['pack']),
    unitPrice: _str(json['unit_price']),
    selectedUnitPrice: _str(json['selected_unit_price']),
    validity: _str(json['validity']),
    imageUrl: _str(json['image_url']),
    sourceUrl: _str(json['source_url']),
  );

  final String retailer;

  /// Every retailer this row stands for. More than one when identical offers
  /// at the same price were folded together by the server.
  final List<String> retailers;

  /// The retailers as one display string, already joined by the server.
  final String retailerLabel;

  final String category;
  final String product;
  final String description;
  final double? regularPrice;
  final String regularPriceText;
  final String regularComparison;
  final String regularComparisonState;
  final String checkoutPriceText;
  final double? effectivePrice;
  final String effectivePriceText;
  final String selectedComparison;
  final String selectedComparisonState;
  final double loyaltySavings;
  final String loyaltySavingsText;
  final String loyaltyBenefit;
  final double? deposit;
  final String depositText;
  final String depositNote;
  final String pack;
  final String unitPrice;
  final String selectedUnitPrice;
  final String validity;
  final String imageUrl;
  final String sourceUrl;

  Map<String, dynamic> toJson() => {
    'retailer': retailer,
    'retailers': retailers,
    'retailer_label': retailerLabel,
    'category': category,
    'product': product,
    'description': description,
    'regular_price': regularPrice,
    'regular_price_text': regularPriceText,
    'regular_comparison': regularComparison,
    'regular_comparison_state': regularComparisonState,
    'checkout_price_text': checkoutPriceText,
    'effective_price': effectivePrice,
    'effective_price_text': effectivePriceText,
    'selected_comparison': selectedComparison,
    'selected_comparison_state': selectedComparisonState,
    'loyalty_savings': loyaltySavings,
    'loyalty_savings_text': loyaltySavingsText,
    'loyalty_benefit': loyaltyBenefit,
    'deposit': deposit,
    'deposit_text': depositText,
    'deposit_note': depositNote,
    'pack': pack,
    'unit_price': unitPrice,
    'selected_unit_price': selectedUnitPrice,
    'validity': validity,
    'image_url': imageUrl,
    'source_url': sourceUrl,
  };

  /// The web interface treats anything above half a cent as a real saving.
  bool get hasSaving => loyaltySavings > 0.004;

  /// True when this row represents the same offer at several retailers.
  bool get isMerged => retailers.length > 1;

  /// What to print in the retailer slot, whether or not the row was merged.
  String get retailerText =>
      retailerLabel.isNotEmpty ? retailerLabel : retailer;

  /// Stable identity for selection. The API exposes no offer id, so this
  /// mirrors the key the web interface builds for its shopping-list picker.
  String get key => '$retailer|$product|$regularPriceText';
}

/// A loyalty program offered for the current result set.
class LoyaltyProgram {
  const LoyaltyProgram({
    required this.id,
    required this.label,
    required this.note,
  });

  factory LoyaltyProgram.fromJson(Map<String, dynamic> json) => LoyaltyProgram(
    id: _str(json['id']),
    label: _str(json['label']),
    note: _str(json['note']),
  );

  final String id;
  final String label;
  final String note;

  Map<String, dynamic> toJson() => {'id': id, 'label': label, 'note': note};
}

/// One page of comparison results, including the filter facets.
class ResultPage {
  ResultPage({
    required this.searchId,
    required this.postalCode,
    required this.cacheAgeSeconds,
    required this.sourceOfferCount,
    required this.filteredOfferCount,
    required this.hiddenCount,
    required this.page,
    required this.pageCount,
    required this.hasNext,
    required this.retailer,
    required this.view,
    required this.retailerCounts,
    required this.category,
    required this.categoryCounts,
    required this.selectedLoyaltyPrograms,
    required this.availableLoyaltyPrograms,
    required this.loyaltyNote,
    required this.warnings,
    required this.offers,
  });

  factory ResultPage.fromJson(Map<String, dynamic> json) => ResultPage(
    searchId: _str(json['search_id']),
    postalCode: _str(json['postal_code']),
    cacheAgeSeconds: _int(json['cache_age_seconds']),
    sourceOfferCount: _int(json['source_offer_count']),
    filteredOfferCount: _int(json['filtered_offer_count']),
    hiddenCount: _int(json['hidden_count']),
    page: _int(json['page']),
    pageCount: _int(json['page_count']),
    hasNext: json['has_next'] == true,
    retailer: _str(json['retailer']),
    view: _str(json['view']),
    retailerCounts: _counts(json['retailer_counts']),
    category: _str(json['category']),
    categoryCounts: _counts(json['category_counts']),
    selectedLoyaltyPrograms: (json['selected_loyalty_programs'] as List? ?? [])
        .map(_str)
        .where((item) => item.isNotEmpty)
        .toList(),
    availableLoyaltyPrograms:
        (json['available_loyalty_programs'] as List? ?? [])
            .whereType<Map<String, dynamic>>()
            .map(LoyaltyProgram.fromJson)
            .toList(),
    loyaltyNote: _str(json['loyalty_note']),
    warnings: (json['warnings'] as List? ?? [])
        .map(_str)
        .where((item) => item.isNotEmpty)
        .toList(),
    offers: (json['offers'] as List? ?? [])
        .whereType<Map<String, dynamic>>()
        .map(Offer.fromJson)
        .toList(),
  );

  final String searchId;
  final String postalCode;
  final int cacheAgeSeconds;
  final int sourceOfferCount;
  final int filteredOfferCount;
  final int hiddenCount;
  final int page;
  final int pageCount;
  final bool hasNext;
  final String retailer;
  final String view;
  final Map<String, int> retailerCounts;
  final String category;
  final Map<String, int> categoryCounts;
  final List<String> selectedLoyaltyPrograms;
  final List<LoyaltyProgram> availableLoyaltyPrograms;
  final String loyaltyNote;
  final List<String> warnings;
  final List<Offer> offers;

  Map<String, dynamic> toJson() => {
    'search_id': searchId,
    'postal_code': postalCode,
    'cache_age_seconds': cacheAgeSeconds,
    'source_offer_count': sourceOfferCount,
    'filtered_offer_count': filteredOfferCount,
    'hidden_count': hiddenCount,
    'page': page,
    'page_count': pageCount,
    'has_next': hasNext,
    'retailer': retailer,
    'view': view,
    'retailer_counts': retailerCounts,
    'category': category,
    'category_counts': categoryCounts,
    'selected_loyalty_programs': selectedLoyaltyPrograms,
    'available_loyalty_programs': availableLoyaltyPrograms
        .map((item) => item.toJson())
        .toList(),
    'loyalty_note': loyaltyNote,
    'warnings': warnings,
    'offers': offers.map((offer) => offer.toJson()).toList(),
  };
}

/// Progress of a running search, as reported by the job endpoint.
class SearchProgress {
  const SearchProgress({
    required this.jobId,
    required this.status,
    required this.step,
    required this.source,
    required this.retailer,
    required this.progress,
    required this.processedSources,
    required this.totalSources,
    required this.processedProducts,
    required this.searchId,
    required this.resultPath,
    required this.error,
  });

  factory SearchProgress.fromJson(Map<String, dynamic> json) => SearchProgress(
    jobId: _str(json['job_id']),
    status: _str(json['status']),
    step: _str(json['step']),
    source: _str(json['source']),
    retailer: _str(json['retailer']),
    progress: _int(json['progress']),
    processedSources: _int(json['processed_sources']),
    totalSources: _int(json['total_sources']),
    processedProducts: _int(json['processed_products']),
    searchId: _str(json['search_id']),
    resultPath: _str(json['result_url']),
    error: _str(json['error']),
  );

  final String jobId;
  final String status;
  final String step;
  final String source;
  final String retailer;
  final int progress;
  final int processedSources;
  final int totalSources;
  final int processedProducts;
  final String searchId;

  /// Server-relative path including the signed result token.
  final String resultPath;
  final String error;

  bool get isDone => status == 'completed';
  bool get isFailed => status == 'failed';
}

/// A shopping list exposed by the server's KitchenOwl integration.
class ShoppingListTarget {
  const ShoppingListTarget({required this.entityId, required this.label});

  factory ShoppingListTarget.fromJson(Map<String, dynamic> json) =>
      ShoppingListTarget(
        entityId: _str(json['entity_id']),
        label: _str(json['label']),
      );

  final String entityId;
  final String label;
}

/// What the server reports about its shopping-list integration.
class ShoppingListInfo {
  const ShoppingListInfo({
    required this.configured,
    required this.targets,
    required this.defaultEntity,
  });

  factory ShoppingListInfo.fromJson(Map<String, dynamic> json) =>
      ShoppingListInfo(
        configured: json['configured'] == true,
        targets: (json['targets'] as List? ?? [])
            .whereType<Map<String, dynamic>>()
            .map(ShoppingListTarget.fromJson)
            .toList(),
        defaultEntity: _str(json['default_entity']),
      );

  static const disabled = ShoppingListInfo(
    configured: false,
    targets: [],
    defaultEntity: '',
  );

  final bool configured;
  final List<ShoppingListTarget> targets;
  final String defaultEntity;
}
