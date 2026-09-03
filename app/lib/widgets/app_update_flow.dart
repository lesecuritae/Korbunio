import 'package:flutter/material.dart';
import 'package:url_launcher/url_launcher.dart';

import '../services/app_update.dart';

/// The dialogs around [AppUpdateService]: offer, download with progress,
/// hand-over to the installer. Started only from the settings; the app never
/// checks on its own.
class AppUpdateFlow {
  AppUpdateFlow({AppUpdateService? service})
    : service = service ?? AppUpdateService();

  final AppUpdateService service;

  Future<void> check(BuildContext context) async {
    await service.cleanupCachedApks();
    final result = await service.check();
    if (!context.mounted) return;
    switch (result.status) {
      case AppUpdateStatus.available:
        await _offer(context, result.info!);
      case AppUpdateStatus.current:
        _snack(context, 'Du bist aktuell (${result.currentVersion}).');
      case AppUpdateStatus.error:
        _snack(context, result.error ?? 'Update-Suche fehlgeschlagen.');
    }
  }

  Future<void> _offer(BuildContext context, AppUpdateInfo info) async {
    final action = await showDialog<String>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: Text('KorbKlar ${info.version} verfügbar'),
        content: SingleChildScrollView(
          child: Text(
            '${info.notes.isEmpty ? 'Eine neue Version ist verfügbar.' : info.notes}\n\n'
            'Die APK (${(info.size / 1024 / 1024).toStringAsFixed(1)} MB) kommt '
            'direkt aus dem GitHub-Release und wird vor der Installation gegen '
            'die dort hinterlegte Prüfsumme geprüft. Android kann beim ersten '
            'Mal fragen, ob KorbKlar unbekannte Apps installieren darf.',
          ),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(ctx, 'later'),
            child: const Text('Später'),
          ),
          if (info.releaseUrl != null)
            TextButton(
              onPressed: () => Navigator.pop(ctx, 'browser'),
              child: const Text('Release öffnen'),
            ),
          FilledButton(
            onPressed: () => Navigator.pop(ctx, 'install'),
            child: const Text('Installieren'),
          ),
        ],
      ),
    );
    if (!context.mounted) return;
    switch (action) {
      case 'browser':
        await launchUrl(info.releaseUrl!, mode: LaunchMode.externalApplication);
      case 'install':
        await _downloadAndInstall(context, info);
    }
  }

  Future<void> _downloadAndInstall(
    BuildContext context,
    AppUpdateInfo info,
  ) async {
    final progress = ValueNotifier<(int, int)>((0, info.size));
    var canceled = false;
    var dialogOpen = true;
    // The progress dialog is closed by the flow itself, so the future is not
    // awaited here; that would block until the user cancels.
    // ignore: unawaited_futures
    showDialog<void>(
      context: context,
      barrierDismissible: false,
      builder: (ctx) => AlertDialog(
        title: const Text('Update wird geladen'),
        content: ValueListenableBuilder<(int, int)>(
          valueListenable: progress,
          builder: (context, value, child) {
            final (received, total) = value;
            final fraction = total > 0
                ? (received / total).clamp(0.0, 1.0)
                : null;
            String mb(int bytes) => (bytes / 1024 / 1024).toStringAsFixed(1);
            return Column(
              mainAxisSize: MainAxisSize.min,
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                LinearProgressIndicator(value: fraction),
                const SizedBox(height: 10),
                Text('${mb(received)} von ${total > 0 ? mb(total) : '?'} MB'),
              ],
            );
          },
        ),
        actions: [
          TextButton(
            onPressed: () {
              canceled = true;
              dialogOpen = false;
              service.cancelDownload();
              Navigator.pop(ctx);
            },
            child: const Text('Abbrechen'),
          ),
        ],
      ),
    );
    try {
      final file = await service.download(info, (received, total) {
        progress.value = (received, total);
      });
      if (!context.mounted || canceled) return;
      if (dialogOpen) {
        dialogOpen = false;
        Navigator.of(context, rootNavigator: true).pop();
      }
      await service.install(file);
    } on AppUpdateException catch (error) {
      if (!context.mounted || canceled) return;
      if (dialogOpen) {
        dialogOpen = false;
        Navigator.of(context, rootNavigator: true).pop();
      }
      _snack(context, error.message);
    } finally {
      progress.dispose();
    }
  }

  void _snack(BuildContext context, String text) {
    ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(text)));
  }

  void close() => service.close();
}
