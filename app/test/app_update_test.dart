import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:korbklar_app/services/app_update.dart';

const _sha = '497df04a44a36054fe9fa78eabb43c1ce887ced6fcfb1e0cff5215b11153f431';

Map<String, dynamic> _release(String tag, {bool withDigest = true}) => {
  'tag_name': tag,
  'html_url': 'https://github.com/lesecuritae/KorbKlar/releases/tag/$tag',
  'body': 'Neue Angebote schneller.',
  'published_at': '2026-09-02T01:55:32Z',
  'assets': [
    for (final abi in ['arm64-v8a', 'armeabi-v7a', 'x86_64'])
      {
        'name': 'app-$abi-release.apk',
        'size': 18917885,
        'browser_download_url':
            'https://github.com/lesecuritae/KorbKlar/releases/download/$tag/app-$abi-release.apk',
        if (withDigest) 'digest': 'sha256:$_sha',
      },
  ],
};

AppUpdateService _service(
  Object body, {
  int status = 200,
  String installed = '0.1.12',
  String abi = 'arm64-v8a',
}) => AppUpdateService(
  client: MockClient((request) async {
    expect(request.url.host, 'api.github.com');
    expect(request.url.path, '/repos/lesecuritae/KorbKlar/releases/latest');
    return http.Response(jsonEncode(body), status);
  }),
  abi: abi,
  installedVersion: () async => installed,
);

void main() {
  group('AppVersion', () {
    test('compares numerically and ignores the tag prefix', () {
      expect(
        AppVersion.tryParse('v0.1.13')! > AppVersion.tryParse('0.1.12')!,
        isTrue,
      );
      expect(
        AppVersion.tryParse('v0.10.0')! > AppVersion.tryParse('0.9.9')!,
        isTrue,
      );
      expect(
        AppVersion.tryParse('1.0')!.compareTo(AppVersion.tryParse('1.0.0')!),
        0,
      );
      expect(AppVersion.tryParse('release'), isNull);
    });
  });

  group('AppUpdateService.check', () {
    test('offers a newer release with the APK for the running ABI', () async {
      final result = await _service(_release('v0.1.13')).check();
      expect(result.status, AppUpdateStatus.available);
      expect(result.info!.apkName, 'app-arm64-v8a-release.apk');
      expect(result.info!.sha256, _sha);
      expect(result.info!.notes, 'Neue Angebote schneller.');
    });

    test('picks the 32-bit APK on an armeabi-v7a phone', () async {
      final result = await _service(
        _release('v0.1.13'),
        abi: 'armeabi-v7a',
      ).check();
      expect(result.info!.apkName, 'app-armeabi-v7a-release.apk');
    });

    test('is current when the installed version matches or is newer', () async {
      expect(
        (await _service(_release('v0.1.12')).check()).status,
        AppUpdateStatus.current,
      );
      expect(
        (await _service(
          _release('v0.1.12'),
          installed: '0.2.0',
        ).check()).status,
        AppUpdateStatus.current,
      );
    });

    test('refuses an asset GitHub has no digest for', () async {
      final result = await _service(
        _release('v0.1.13', withDigest: false),
      ).check();
      expect(result.status, AppUpdateStatus.error);
      expect(result.error, contains('Prüfsumme'));
    });

    test('reports API failures without throwing', () async {
      final missing = await _service({
        'message': 'Not Found',
      }, status: 404).check();
      expect(missing.status, AppUpdateStatus.error);
      expect(missing.error, 'Noch kein Release veröffentlicht.');
      final limited = await _service({
        'message': 'rate limit',
      }, status: 403).check();
      expect(limited.error, 'GitHub antwortet mit HTTP 403.');
    });
  });
}
