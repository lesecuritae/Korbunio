import 'package:flutter/material.dart';

/// Colour tokens taken verbatim from the web interface so the app and the
/// browser view read as one product. The web stylesheets define these as CSS
/// custom properties in `home.css` and `results.css`.
@immutable
class KorbColors extends ThemeExtension<KorbColors> {
  const KorbColors({
    required this.bg,
    required this.panel,
    required this.text,
    required this.muted,
    required this.line,
    required this.accent,
    required this.chip,
    required this.good,
    required this.error,
  });

  final Color bg;
  final Color panel;
  final Color text;
  final Color muted;
  final Color line;
  final Color accent;
  final Color chip;
  final Color good;
  final Color error;

  static const light = KorbColors(
    bg: Color(0xFFF4F7F5),
    panel: Color(0xFFFFFFFF),
    text: Color(0xFF14201B),
    muted: Color(0xFF63716A),
    line: Color(0xFFDCE5E0),
    accent: Color(0xFF116149),
    chip: Color(0xFFE4F2EB),
    good: Color(0xFF116149),
    error: Color(0xFFB42318),
  );

  static const dark = KorbColors(
    bg: Color(0xFF111318),
    panel: Color(0xFF191C22),
    text: Color(0xFFF1F3F5),
    muted: Color(0xFFAAB1BC),
    line: Color(0xFF303641),
    accent: Color(0xFF72D5A6),
    chip: Color(0xFF20352D),
    good: Color(0xFF72D5A6),
    error: Color(0xFFFF938A),
  );

  @override
  KorbColors copyWith({
    Color? bg,
    Color? panel,
    Color? text,
    Color? muted,
    Color? line,
    Color? accent,
    Color? chip,
    Color? good,
    Color? error,
  }) {
    return KorbColors(
      bg: bg ?? this.bg,
      panel: panel ?? this.panel,
      text: text ?? this.text,
      muted: muted ?? this.muted,
      line: line ?? this.line,
      accent: accent ?? this.accent,
      chip: chip ?? this.chip,
      good: good ?? this.good,
      error: error ?? this.error,
    );
  }

  @override
  KorbColors lerp(ThemeExtension<KorbColors>? other, double t) {
    if (other is! KorbColors) return this;
    return KorbColors(
      bg: Color.lerp(bg, other.bg, t)!,
      panel: Color.lerp(panel, other.panel, t)!,
      text: Color.lerp(text, other.text, t)!,
      muted: Color.lerp(muted, other.muted, t)!,
      line: Color.lerp(line, other.line, t)!,
      accent: Color.lerp(accent, other.accent, t)!,
      chip: Color.lerp(chip, other.chip, t)!,
      good: Color.lerp(good, other.good, t)!,
      error: Color.lerp(error, other.error, t)!,
    );
  }
}

extension KorbColorsOf on BuildContext {
  KorbColors get colors => Theme.of(this).extension<KorbColors>()!;
}

ThemeData _build(KorbColors c, Brightness brightness) {
  final scheme =
      ColorScheme.fromSeed(
        seedColor: c.accent,
        brightness: brightness,
      ).copyWith(
        surface: c.bg,
        onSurface: c.text,
        primary: c.accent,
        error: c.error,
      );

  return ThemeData(
    useMaterial3: true,
    brightness: brightness,
    colorScheme: scheme,
    scaffoldBackgroundColor: c.bg,
    extensions: [c],
    // The web interface uses the platform UI font rather than a bundled face.
    fontFamily: null,
    dividerTheme: DividerThemeData(color: c.line, thickness: 1, space: 1),
    cardTheme: CardThemeData(
      color: c.panel,
      elevation: 0,
      margin: EdgeInsets.zero,
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(14),
        side: BorderSide(color: c.line),
      ),
    ),
    inputDecorationTheme: InputDecorationTheme(
      filled: true,
      fillColor: c.panel,
      contentPadding: const EdgeInsets.symmetric(horizontal: 14, vertical: 12),
      border: OutlineInputBorder(
        borderRadius: BorderRadius.circular(10),
        borderSide: BorderSide(color: c.line),
      ),
      enabledBorder: OutlineInputBorder(
        borderRadius: BorderRadius.circular(10),
        borderSide: BorderSide(color: c.line),
      ),
      focusedBorder: OutlineInputBorder(
        borderRadius: BorderRadius.circular(10),
        borderSide: BorderSide(color: c.accent, width: 2),
      ),
      hintStyle: TextStyle(color: c.muted),
    ),
    filledButtonTheme: FilledButtonThemeData(
      style: FilledButton.styleFrom(
        backgroundColor: c.accent,
        foregroundColor: brightness == Brightness.dark
            ? const Color(0xFF10231B)
            : Colors.white,
        minimumSize: const Size(0, 48),
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
        textStyle: const TextStyle(fontSize: 16, fontWeight: FontWeight.w600),
      ),
    ),
    snackBarTheme: SnackBarThemeData(
      backgroundColor: c.panel,
      contentTextStyle: TextStyle(color: c.text),
      behavior: SnackBarBehavior.floating,
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
    ),
  );
}

ThemeData korbLightTheme() => _build(KorbColors.light, Brightness.light);
ThemeData korbDarkTheme() => _build(KorbColors.dark, Brightness.dark);
