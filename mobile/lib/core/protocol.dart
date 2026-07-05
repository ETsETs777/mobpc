class MobpcCommand {
  MobpcCommand({
    required this.id,
    required this.type,
    this.payload = const {},
  });

  final String id;
  final String type;
  final Map<String, dynamic> payload;

  Map<String, dynamic> toJson() => {
        'id': id,
        'type': type,
        'payload': payload,
      };
}

class MobpcResponse {
  MobpcResponse({
    required this.id,
    required this.ok,
    this.data,
    this.error,
  });

  final String? id;
  final bool ok;
  final Map<String, dynamic>? data;
  final String? error;

  factory MobpcResponse.fromJson(Map<String, dynamic> json) {
    return MobpcResponse(
      id: json['id'] as String?,
      ok: json['ok'] as bool? ?? false,
      data: json['data'] as Map<String, dynamic>?,
      error: json['error'] as String?,
    );
  }
}

class PairingPayload {
  PairingPayload({
    required this.host,
    required this.port,
    required this.code,
  });

  final String host;
  final int port;
  final String code;

  factory PairingPayload.fromJson(Map<String, dynamic> json) {
    return PairingPayload(
      host: json['host'] as String,
      port: json['port'] as int,
      code: json['code'] as String,
    );
  }
}

class ConnectionProfile {
  ConnectionProfile({
    required this.name,
    required this.host,
    required this.port,
    required this.token,
    this.useTls = false,
  });

  final String name;
  final String host;
  final int port;
  final String token;
  final bool useTls;

  String get wsUrl {
    final scheme = useTls ? 'wss' : 'ws';
    return '$scheme://$host:$port/ws?token=$token';
  }

  String get httpBase {
    final scheme = useTls ? 'https' : 'http';
    return '$scheme://$host:$port';
  }

  Map<String, dynamic> toJson() => {
        'name': name,
        'host': host,
        'port': port,
        'token': token,
        'useTls': useTls,
      };

  factory ConnectionProfile.fromJson(Map<String, dynamic> json) {
    return ConnectionProfile(
      name: json['name'] as String,
      host: json['host'] as String,
      port: json['port'] as int,
      token: json['token'] as String,
      useTls: json['useTls'] as bool? ?? false,
    );
  }
}
