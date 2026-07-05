import 'dart:async';
import 'dart:convert';

import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:uuid/uuid.dart';
import 'package:web_socket_channel/web_socket_channel.dart';

import 'protocol.dart';

enum ConnectionState { disconnected, connecting, connected, error }

class MobpcClient {
  MobpcClient();

  WebSocketChannel? _channel;
  final _pending = <String, Completer<MobpcResponse>>{};
  final _eventController = StreamController<Map<String, dynamic>>.broadcast();
  final _stateController = StreamController<ConnectionState>.broadcast();

  ConnectionState _state = ConnectionState.disconnected;
  ConnectionProfile? _profile;

  Stream<Map<String, dynamic>> get events => _eventController.stream;
  Stream<ConnectionState> get stateChanges => _stateController.stream;
  ConnectionState get state => _state;
  ConnectionProfile? get profile => _profile;

  Future<void> connect(ConnectionProfile profile) async {
    await disconnect();
    _profile = profile;
    _setState(ConnectionState.connecting);
    try {
      _channel = WebSocketChannel.connect(Uri.parse(profile.wsUrl));
      _channel!.stream.listen(_onMessage, onError: _onError, onDone: _onDone);
      await Future.delayed(const Duration(milliseconds: 500));
      _setState(ConnectionState.connected);
    } catch (e) {
      _setState(ConnectionState.error);
      rethrow;
    }
  }

  Future<void> disconnect() async {
    await _channel?.sink.close();
    _channel = null;
    for (final c in _pending.values) {
      if (!c.isCompleted) c.completeError('Disconnected');
    }
    _pending.clear();
    _setState(ConnectionState.disconnected);
  }

  Future<MobpcResponse> send(
    String type, {
    Map<String, dynamic> payload = const {},
    Duration timeout = const Duration(seconds: 30),
  }) async {
    if (_channel == null) throw StateError('Not connected');
    final id = const Uuid().v4();
    final cmd = MobpcCommand(id: id, type: type, payload: payload);
    final completer = Completer<MobpcResponse>();
    _pending[id] = completer;
    _channel!.sink.add(jsonEncode(cmd.toJson()));
    return completer.future.timeout(timeout, onTimeout: () {
      _pending.remove(id);
      throw TimeoutException('Command $type timed out');
    });
  }

  void _onMessage(dynamic raw) {
    try {
      final json = jsonDecode(raw as String) as Map<String, dynamic>;
      if (json.containsKey('type') && !json.containsKey('ok')) {
        _eventController.add(json);
        return;
      }
      final response = MobpcResponse.fromJson(json);
      final id = response.id;
      if (id != null && _pending.containsKey(id)) {
        _pending.remove(id)!.complete(response);
      }
    } catch (_) {}
  }

  void _onError(Object error) {
    _setState(ConnectionState.error);
    _eventController.add({'type': 'error', 'data': {'message': error.toString()}});
  }

  void _onDone() {
    _setState(ConnectionState.disconnected);
  }

  void _setState(ConnectionState s) {
    _state = s;
    if (!_stateController.isClosed) _stateController.add(s);
  }

  void dispose() {
    disconnect();
    _eventController.close();
    _stateController.close();
  }
}

final mobpcClientProvider = Provider<MobpcClient>((ref) {
  final client = MobpcClient();
  ref.onDispose(client.dispose);
  return client;
});
