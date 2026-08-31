import 'package:geocoding/geocoding.dart';
import 'package:geolocator/geolocator.dart';

class PostalLocationException implements Exception {
  PostalLocationException(this.message);
  final String message;
  @override
  String toString() => message;
}

/// Resolves the current Android location to a postal code once. Coordinates
/// are returned by the OS location service, used for reverse geocoding, and
/// immediately discarded; KorbKlar persists only the resulting postal code.
class PostalLocationResolver {
  Future<String> resolve() async {
    if (!await Geolocator.isLocationServiceEnabled()) {
      throw PostalLocationException('Bitte aktiviere die Standortdienste.');
    }
    var permission = await Geolocator.checkPermission();
    if (permission == LocationPermission.denied) {
      permission = await Geolocator.requestPermission();
    }
    if (permission == LocationPermission.denied) {
      throw PostalLocationException('Standortfreigabe wurde nicht erteilt.');
    }
    if (permission == LocationPermission.deniedForever) {
      throw PostalLocationException(
        'Standortzugriff ist dauerhaft gesperrt. Bitte in den Android-Einstellungen freigeben.',
      );
    }
    final position = await Geolocator.getCurrentPosition(
      locationSettings: const LocationSettings(
        accuracy: LocationAccuracy.medium,
        timeLimit: Duration(seconds: 20),
      ),
    );
    final places = await placemarkFromCoordinates(
      position.latitude,
      position.longitude,
    );
    for (final place in places) {
      final postalCode = (place.postalCode ?? '').trim();
      if (RegExp(r'^\d{5}$').hasMatch(postalCode)) return postalCode;
    }
    throw PostalLocationException(
      'Für den aktuellen Standort wurde keine deutsche PLZ gefunden.',
    );
  }
}
