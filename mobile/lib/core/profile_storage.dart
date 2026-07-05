import 'dart:convert';

import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:http/http.dart' as http;

import 'protocol.dart';

const _storageKey = 'mobpc_profiles';

class ProfileStorage {
  ProfileStorage(this._storage);

  final FlutterSecureStorage _storage;

  Future<List<ConnectionProfile>> load() async {
    final raw = await _storage.read(key: _storageKey);
    if (raw == null || raw.isEmpty) return [];
    final list = jsonDecode(raw) as List<dynamic>;
    return list
        .map((e) => ConnectionProfile.fromJson(e as Map<String, dynamic>))
        .toList();
  }

  Future<void> save(List<ConnectionProfile> profiles) async {
    final encoded = jsonEncode(profiles.map((p) => p.toJson()).toList());
    await _storage.write(key: _storageKey, value: encoded);
  }

  Future<void> add(ConnectionProfile profile) async {
    final profiles = await load();
    profiles.removeWhere((p) => p.name == profile.name);
    profiles.insert(0, profile);
    await save(profiles);
  }
}

final profileStorageProvider = Provider<ProfileStorage>(
  (ref) => ProfileStorage(const FlutterSecureStorage()),
);

final profilesProvider =
    StateNotifierProvider<ProfilesNotifier, List<ConnectionProfile>>(
  (ref) => ProfilesNotifier(ref.read(profileStorageProvider)),
);

class ProfilesNotifier extends StateNotifier<List<ConnectionProfile>> {
  ProfilesNotifier(this._storage) : super([]) {
    _load();
  }

  final ProfileStorage _storage;

  Future<void> _load() async {
    state = await _storage.load();
  }

  Future<void> add(ConnectionProfile profile) async {
    await _storage.add(profile);
    state = await _storage.load();
  }
}

Future<ConnectionProfile> exchangePairingCode({
  required String host,
  required int port,
  required String code,
  String deviceName = 'mobile',
  bool useTls = false,
}) async {
  final scheme = useTls ? 'https' : 'http';
  final url = Uri.parse('$scheme://$host:$port/api/pairing/exchange');
  final response = await http.post(
    url,
    headers: {'Content-Type': 'application/json'},
    body: jsonEncode({'code': code, 'device_name': deviceName}),
  );
  if (response.statusCode != 200) {
    throw Exception('Pairing failed: ${response.body}');
  }
  final data = jsonDecode(response.body) as Map<String, dynamic>;
  return ConnectionProfile(
    name: data['device_name'] as String? ?? deviceName,
    host: host,
    port: port,
    token: data['token'] as String,
    useTls: useTls,
  );
}
