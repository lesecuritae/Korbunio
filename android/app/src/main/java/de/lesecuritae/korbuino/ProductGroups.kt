package de.lesecuritae.korbuino

import java.text.Normalizer
import java.util.Locale
import java.util.regex.Pattern

/**
 * The product groups ("Warengruppen") of the offer list, e.g. "Obst & Gemüse".
 *
 * The rules are the ones of the server (src/supermarkt/categories.py), so the
 * app and the server sort an offer into the same group. The retailers name
 * their own categories differently ("Exotische Früchte", "Prospektseite 23");
 * this maps them onto one shared list.
 */
object ProductGroups {
    const val OTHER = "Weitere Angebote"

    /** The groups in the order of a walk through a shop; unknown ones go last. */
    val ORDER: List<String> = listOf(
        "Obst & Gemüse",
        "Fleisch & Wurst",
        "Fisch & Meeresfrüchte",
        "Molkereiprodukte & Eier",
        "Backwaren",
        "Kühlprodukte",
        "Tiefkühl / Eis & Dessert",
        "Vorräte & Grundnahrungsmittel",
        "Konserven & Fertiggerichte",
        "Frühstück & Brotaufstriche",
        "Getränke",
        "Snacks",
        "Drogerie & Körperpflege",
        "Haushalt & Reinigung",
        "Tierbedarf",
        "Baby & Kind",
        "Wohnen, Freizeit & Non-Food",
        "Weitere Angebote",
    )

    // Concrete product kinds precede terms which can merely describe a flavour.
    private val productRules: List<Pair<String, Regex>> = listOf(
        // "eis" nur als Speiseeis: das frühere \w*eis traf auch Reis, Preis und Hinweis (Netto: "HINWEIS: MIT NETTO PLUS APP ...").
        "Tiefkühl / Eis & Dessert" to """\b(?:ice cream|eiscreme|eisbecher|eiskonfekt|eistorte|eiskugel|eiswaffel|speiseeis|stieleis|wassereis|softeis|milcheis|sahneeis|cremeeis|fruchteis|joghurteis|vanilleeis|schokoladeneis|erdbeereis|gelato|calippo|pirulo|dessert|mousse|eis)\b""",
        "Haushalt & Reinigung" to """\b(?:bodenkehrer|kehrmaschine|besen|wischmopp|staubsauger|wc reiniger|\w*reiniger|grillanzuender|grillanzünder)\b""",
        "Tierbedarf" to """\b(?:katzenfutter|hundefutter|katzenstreu|tierzubehoer|tierzubehör|tierfutter)\b""",
        "Snacks" to """\b(?:pom bär|pom baer|chips|flips|knabber\w*|snacks?|smarties|chocolate|schokolade)\b""",
        "Backwaren" to """\b(?:brot|\w*broetchen|\w*brötchen|kuchen|croissant|breze\w*|pain au chocolat|gebaeck|gebäck)\b""",
        "Getränke" to """\b(?:cola|limonade|wasser|\w*saft|bier|wein|spirituose|kaffee|tee)\b""",
        "Obst & Gemüse" to """\b(?:obst|gemuese|gemüse|salat|rucola|kartoffel\w*|tomat\w*|apfel|banane\w*)\b""",
        "Fleisch & Wurst" to """\b(?:fleisch|wurst|schinken|salami|gefluegel|geflügel|hackfleisch)\b""",
        "Fisch & Meeresfrüchte" to """\b(?:fisch|lachs|thunfisch|meeresfr\w*|garnele\w*)\b""",
        "Molkereiprodukte & Eier" to """\b(?:milch|kaese|käse|joghurt|quark|butter|eier?)\b""",
        "Konserven & Fertiggerichte" to """\b(?:konserve|fertiggericht|instant|suppe)\b""",
        "Frühstück & Brotaufstriche" to """\b(?:marmelade|honig|muesli|müsli|cerealien|brotaufstrich)\b""",
        "Drogerie & Körperpflege" to """\b(?:koerperpflege|körperpflege|hygiene|kosmetik|shampoo)\b""",
        "Baby & Kind" to """\b(?:baby|windel\w*)\b""",
        "Vorräte & Grundnahrungsmittel" to """\b(?:nudeln?|reis|mehl|zucker|gewuerz|gewürz|backzutat)\b""",
    ).map { it.first to compile(it.second) }

    private val sourceRules: List<Pair<String, Regex>> = listOf(
        "Obst & Gemüse" to """obst|gemuese|gemüse|salat|(?<!meeres)frucht|(?<!meeres)fruechte|(?<!meeres)früchte|beere|zitrus|melone""",
        "Fleisch & Wurst" to """fleisch|wurst|wuerst|würst|gefluegel|geflügel|steak|schnitzel""",
        "Fisch & Meeresfrüchte" to """fisch|meeresfr""",
        "Molkereiprodukte & Eier" to """molkerei|milch|kaese|käse|eier|sahne|schmand|joghurt|jogurt|quark|butter|frischk""",
        "Tiefkühl / Eis & Dessert" to """tiefkuehl|tiefkühl|tk\b|eiscreme|speiseeis|dessert|\beis\b""",
        "Backwaren" to """backwaren|baeck|bäck|brot""",
        "Kühlprodukte" to """kuehl|kühl|frische convenience|feinkost""",
        "Konserven & Fertiggerichte" to """konserve|fertiggericht|instant""",
        "Frühstück & Brotaufstriche" to """fruehst|frühst|brotaufstrich|muesli|müsli|cerealien""",
        "Getränke" to """getraenk|getränk|bier|wein|spirituose|wasser\b|saft|limonade|softdrink|cocktail|sekt|prosecco|likoer|likör|schnaps|whisk|aperitif""",
        "Snacks" to """\bsnacks?\b|chips|knabber|flips""",
        "Snacks" to """suess|süss|schokolade|keks|bonbon""",
        "Drogerie & Körperpflege" to """drogerie|koerper|körper|pflege|hygiene|kosmetik""",
        "Haushalt & Reinigung" to """haushalt|reinig|waschmittel|spuel|spül|papier|putz""",
        "Tierbedarf" to """tier|hund|katze|haustier""",
        "Baby & Kind" to """baby|kind|windel""",
        "Wohnen, Freizeit & Non-Food" to """non.?food|wohnen|freizeit|garten|textil|mode|technik|werkzeug|spielzeug|pflanze|blume|topf|toepfe|töpfe|aufbewahr|behaelter|behälter|kuechenzubehoer|küchenzubehör|kuechengeraet|küchengerät|geschirr|dekoration|sport|filtersystem""",
        "Vorräte & Grundnahrungsmittel" to """vorrat|grundnahr|nudel|reis|mehl|zucker|oel|öl|gewuerz|gewürz|backzutat|\bdip|mayonnaise|senf|ketchup""",
    ).map { it.first to compile(it.second) }

    // Android's ICU regex refuses UNICODE_CHARACTER_CLASS but already treats \w and \b as Unicode;
    // the JVM (unit tests) needs the flag for umlauts.
    private fun compile(pattern: String): Regex = try {
        Pattern.compile(pattern, Pattern.UNICODE_CHARACTER_CLASS).toRegex()
    } catch (_: IllegalArgumentException) {
        Pattern.compile(pattern).toRegex()
    }

    private fun fold(value: String?): String =
        Normalizer.normalize(value.orEmpty(), Normalizer.Form.NFKC)
            .lowercase(Locale.ROOT)
            .replace(Regex("[^\\p{L}\\p{N}_äöüß]+"), " ")
            .trim()

    private fun firstMatch(value: String?, rules: List<Pair<String, Regex>>): String {
        val folded = fold(value)
        if (folded.isEmpty()) return ""
        return rules.firstOrNull { (_, regex) -> regex.containsMatchIn(folded) }?.first.orEmpty()
    }

    private fun fromSource(sourceCategory: String?): String {
        val source = fold(sourceCategory)
        if (source.isEmpty()) return OTHER
        ORDER.firstOrNull { source == fold(it) }?.let { return it }
        if (source == fold("Tiefkühlkost")) return "Tiefkühl / Eis & Dessert"
        return sourceRules.firstOrNull { (_, regex) -> regex.containsMatchIn(source) }?.first ?: OTHER
    }

    /** The group of an offer: what the product name says wins over the retailer's category. */
    fun of(sourceCategory: String?, productName: String?): String =
        firstMatch(productName, productRules).ifEmpty { fromSource(sourceCategory) }

    /** Position in [ORDER]; a group nobody knows sorts after all of them. */
    fun rank(group: String): Int = ORDER.indexOf(group).takeIf { it >= 0 } ?: ORDER.size
}
