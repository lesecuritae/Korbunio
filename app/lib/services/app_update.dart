import 'dart:async';
import 'dart:convert';
import 'dart:ffi' show Abi;
import 'dart:io';

import 'package:crypto/crypto.dart';
import 'package:http/http.dart' as http;
import 'package:open_filex/open_filex.dart';
import 'package:package_info_plus/package_info_plus.dart';
import 'package:path_provider/path_provider.dart';

/// Where the app is published. The releases of this repository carry one
/// signed APK per ABI, and GitHub records a SHA-256 digest for each asset.
const String kUpdateRepository = 'lesecuritae/KorbKlar';

enum AppUpdateStatus { available, current, error }

class AppUpdateException implements Exception {
  const AppUpdateException(this.message);

  final String message;

  @override
  String toString() => message;
}

/// A release version such as `0.1.12`, parsed from a tag like `v0.1.12`.
class AppVersion implements Comparable<AppVersion> {
  const AppVersion(this.parts);

  final List<int> parts;

  static AppVersion? tryParse(String raw) {
    final match = RegExp(r'(\d+(?:\.\d+)*)').firstMatch(raw.trim());
    if (match == null) return null;
    return AppVersion(
      match.group(1)!.split('.').map(int.parse).toList(growable: false),
    );
  }

  @override
  int compareTo(AppVersion other) {
    final length = parts.length > other.parts.length
        ? parts.length
        : other.parts.length;
    for (var i = 0; i < length; i++) {
      final mine = i < parts.length ? parts[i] : 0;
      final theirs = i < other.parts.length ? other.parts[i] : 0;
      if (mine != theirs) return mine.compareTo(theirs);
    }
    return 0;
  }

  bool operator >(AppVersion other) => compareTo(other) > 0;

  @override
  String toString() => parts.join('.');
}

class AppUpdateInfo {
  const AppUpdateInfo({
    required this.version,
    required this.tag,
    required this.apkUrl,
    required this.apkName,
    required this.sha256,
    required this.size,
    required this.notes,
    required this.releaseUrl,
    required this.date,
  });

  final AppVersion version;
  final String tag;
  final Uri apkUrl;
  final String apkName;
  final String sha256;
  final int size;
  final String notes;
  final Uri? releaseUrl;
  final DateTime? date;

  /// Reads one entry of the GitHub releases API and picks the APK built for
  /// [abi] (`arm64-v8a`, `armeabi-v7a`, `x86_64`). A universal APK is taken
  /// when no split one matches.
  factory AppUpdateInfo.fromRelease(Map<String, dynamic> json, String abi) {
    final tag = json['tag_name']?.toString().trim() ?? '';
    final version = AppVersion.tryParse(tag);
    if (version == null) {
      throw const FormatException('Release ohne erkennbare Versionsnummer.');
    }
    final assets = (json['assets'] as List<dynamic>? ?? const [])
        .whereType<Map<String, dynamic>>()
        .where((a) => (a['name']?.toString() ?? '').endsWith('.apk'))
        .toList(growable: false);
    if (assets.isEmpty) {
      throw const FormatException('Das Release enthält keine APK.');
    }
    final asset = assets.firstWhere(
      (a) => a['name'].toString().contains('-$abi-'),
      orElse: () => assets.firstWhere(
        (a) => a['name'].toString().contains('universal'),
        orElse: () => throw FormatException('Keine APK für $abi im Release.'),
      ),
    );
    final digest = asset['digest']?.toString().trim().toLowerCase() ?? '';
    final hash = digest.startsWith('sha256:') ? digest.substring(7) : '';
    if (!RegExp(r'^[0-9a-f]{64}$').hasMatch(hash)) {
      throw const FormatException('Release-APK ohne SHA-256-Prüfsumme.');
    }
    final url = Uri.tryParse(asset['browser_download_url']?.toString() ?? '');
    final size = (asset['size'] as num?)?.toInt() ?? 0;
    if (url == null || !url.hasScheme || size < 1) {
      throw const FormatException('Release-APK ohne gültigen Download.');
    }
    return AppUpdateInfo(
      version: version,
      tag: tag,
      apkUrl: url,
      apkName: asset['name'].toString(),
      sha256: hash,
      size: size,
      notes: json['body']?.toString().trim() ?? '',
      releaseUrl: Uri.tryParse(json['html_url']?.toString() ?? ''),
      date: DateTime.tryParse(json['published_at']?.toString() ?? ''),
    );
  }
}

class AppUpdateResult {
  const AppUpdateResult._({
    required this.status,
    required this.currentVersion,
    this.info,
    this.error,
  });

  factory AppUpdateResult.available(AppUpdateInfo info, String current) =>
      AppUpdateResult._(
        status: AppUpdateStatus.available,
        info: info,
        currentVersion: current,
      );

  factory AppUpdateResult.current(String current, {AppUpdateInfo? info}) =>
      AppUpdateResult._(
        status: AppUpdateStatus.current,
        info: info,
        currentVersion: current,
      );

  factory AppUpdateResult.error(String message) => AppUpdateResult._(
    status: AppUpdateStatus.error,
    currentVersion: '',
    error: message,
  );

  final AppUpdateStatus status;
  final AppUpdateInfo? info;
  final String currentVersion;
  final String? error;
}

typedef UpdateProgress = void Function(int receivedBytes, int totalBytes);

/// Checks GitHub releases for a newer APK, downloads it, verifies the digest
/// GitHub publishes for the asset and hands the file to Android's installer.
///
/// Only Android can install an APK, so the whole feature is inert elsewhere.
class AppUpdateService {
  AppUpdateService({
    this.repository = kUpdateRepository,
    http.Client? client,
    String? abi,
    Future<String> Function()? installedVersion,
  }) : _client = client ?? http.Client(),
       _abi = abi ?? currentAbi(),
       _installedVersion = installedVersion ?? _packageVersion;

  final String repository;
  final http.Client _client;
  final String _abi;
  final Future<String> Function() _installedVersion;
  bool _cancelDownload = false;

  static bool get supported => Platform.isAndroid;

  Uri get latestReleaseUri =>
      Uri.parse('https://api.github.com/repos/$repository/releases/latest');

  /// The ABI name Flutter uses for split APKs, derived from the running
  /// binary so no extra plugin is needed.
  static String currentAbi() {
    final abi = Abi.current();
    if (abi == Abi.androidArm64) return 'arm64-v8a';
    if (abi == Abi.androidArm) return 'armeabi-v7a';
    if (abi == Abi.androidX64) return 'x86_64';
    if (abi == Abi.androidIA32) return 'x86';
    return 'arm64-v8a';
  }

  static Future<String> _packageVersion() async =>
      (await PackageInfo.fromPlatform()).version;

  static bool isNewer(
    AppVersion remote,
    AppVersion local,
    String skippedTag,
    String remoteTag,
  ) => remote > local && remoteTag != skippedTag;

  Future<AppUpdateResult> check({String skippedTag = ''}) async {
    try {
      final current = await _installedVersion();
      final local = AppVersion.tryParse(current) ?? const AppVersion([0]);
      final response = await _client
          .get(
            latestReleaseUri,
            headers: const {
              'Accept': 'application/vnd.github+json',
              'X-GitHub-Api-Version': '2022-11-28',
            },
          )
          .timeout(const Duration(seconds: 10));
      if (response.statusCode == HttpStatus.notFound) {
        throw const AppUpdateException('Noch kein Release veröffentlicht.');
      }
      if (response.statusCode != HttpStatus.ok) {
        throw AppUpdateException(
          'GitHub antwortet mit HTTP ${response.statusCode}.',
        );
      }
      final decoded = jsonDecode(utf8.decode(response.bodyBytes));
      if (decoded is! Map<String, dynamic>) {
        throw const FormatException(
          'Release-Antwort hat ein ungültiges Format.',
        );
      }
      final info = AppUpdateInfo.fromRelease(decoded, _abi);
      if (isNewer(info.version, local, skippedTag, info.tag)) {
        return AppUpdateResult.available(info, current);
      }
      return AppUpdateResult.current(current, info: info);
    } catch (e) {
      return AppUpdateResult.error(_friendlyError(e));
    }
  }

  void cancelDownload() => _cancelDownload = true;

  Future<File> download(AppUpdateInfo info, UpdateProgress onProgress) async {
    _cancelDownload = false;
    final dir = await getTemporaryDirectory();
    final file = File('${dir.path}/korbklar-update-${info.tag}-$_abi.apk');
    if (await file.exists()) await file.delete();
    final sink = file.openWrite();
    var received = 0;
    try {
      final response = await _client
          .send(http.Request('GET', info.apkUrl))
          .timeout(const Duration(seconds: 15));
      if (response.statusCode != HttpStatus.ok) {
        throw AppUpdateException(
          'Download fehlgeschlagen (HTTP ${response.statusCode}).',
        );
      }
      final total = (response.contentLength ?? 0) > 0
          ? response.contentLength!
          : info.size;
      await for (final chunk in response.stream) {
        if (_cancelDownload) {
          throw const AppUpdateException('Download abgebrochen.');
        }
        sink.add(chunk);
        received += chunk.length;
        onProgress(received, total);
      }
      await sink.flush();
      await sink.close();
      if (_cancelDownload) {
        throw const AppUpdateException('Download abgebrochen.');
      }
      final digest = await sha256.bind(file.openRead()).first;
      if (digest.toString().toLowerCase() != info.sha256) {
        throw const AppUpdateException(
          'Die Prüfsumme der APK stimmt nicht. Die Datei wurde verworfen.',
        );
      }
      return file;
    } catch (e) {
      await sink.close().catchError((_) {});
      if (await file.exists()) await file.delete();
      if (e is AppUpdateException) rethrow;
      throw AppUpdateException(_friendlyError(e));
    }
  }

  Future<void> install(File file) async {
    if (!supported) {
      throw const AppUpdateException(
        'Die direkte Installation ist nur unter Android möglich.',
      );
    }
    final result = await OpenFilex.open(
      file.path,
      type: 'application/vnd.android.package-archive',
    );
    if (result.type != ResultType.done) {
      throw AppUpdateException(
        result.message.isEmpty
            ? 'Android-Installer konnte nicht geöffnet werden.'
            : result.message,
      );
    }
  }

  /// Removes APKs left over from earlier updates. Best effort: it must never
  /// disturb app startup.
  Future<void> cleanupCachedApks() async {
    try {
      final dir = await getTemporaryDirectory();
      await for (final entity in dir.list()) {
        if (entity is File &&
            entity.uri.pathSegments.last.startsWith('korbklar-update-') &&
            entity.path.endsWith('.apk')) {
          await entity.delete();
        }
      }
    } catch (_) {}
  }

  void close() => _client.close();

  static String _friendlyError(Object error) {
    if (error is AppUpdateException) return error.message;
    if (error is TimeoutException) return 'Zeitüberschreitung bei GitHub.';
    if (error is FormatException) return error.message;
    return 'GitHub ist nicht erreichbar.';
  }
}
