import 'dart:async';
import 'dart:convert';

import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:uuid/uuid.dart';
import 'package:web_socket_channel/web_socket_channel.dart';

import 'protocol.dart';

enum ConnectionState { disconnected, connecting, connected, reconnecting, error }

class MobpcClient {
  MobpcClient();

  WebSocketChannel? _channel;
  final _pending = <String, Completer<MobpcResponse>>{};
  final _eventController = StreamController<Map<String, dynamic>>.broadcast();
  final _stateController = StreamController<ConnectionState>.broadcast();

  ConnectionState _state = ConnectionState.disconnected;
  ConnectionProfile? _profile;
  StreamSubscription? _streamSub;
  Timer? _reconnectTimer;
  int _reconnectAttempts = 0;
  static const _maxReconnectAttempts = 10;
  bool _autoReconnect = true;

  Stream<Map<String, dynamic>> get events => _eventController.stream;
  Stream<ConnectionState> get stateChanges => _stateController.stream;
  ConnectionState get state => _state;
  ConnectionProfile? get profile => _profile;

  Future<void> connect(ConnectionProfile profile, {bool autoReconnect = true}) async {
    _autoReconnect = autoReconnect;
    _profile = profile;
    await _connectInternal();
  }

  Future<void> _connectInternal() async {
    if (_profile == null) return;
    await _closeChannel();
    _setState(
      _reconnectAttempts > 0
          ? ConnectionState.reconnecting
          : ConnectionState.connecting,
    );
    try {
      _channel = WebSocketChannel.connect(Uri.parse(_profile!.wsUrl));
      _streamSub = _channel!.stream.listen(_onMessage, onError: _onError, onDone: _onDone);
      await Future.delayed(const Duration(milliseconds: 500));
      _reconnectAttempts = 0;
      _setState(ConnectionState.connected);
    } catch (e) {
      _setState(ConnectionState.error);
      _scheduleReconnect();
      rethrow;
    }
  }

  Future<void> disconnect() async {
    _autoReconnect = false;
    _reconnectTimer?.cancel();
    await _closeChannel();
    _setState(ConnectionState.disconnected);
  }

  Future<void> _closeChannel() async {
    _reconnectTimer?.cancel();
    await _streamSub?.cancel();
    _streamSub = null;
    await _channel?.sink.close();
    _channel = null;
    for (final c in _pending.values) {
      if (!c.isCompleted) c.completeError('Disconnected');
    }
    _pending.clear();
  }

  void _scheduleReconnect() {
    if (!_autoReconnect || _profile == null) return;
    if (_reconnectAttempts >= _maxReconnectAttempts) {
      _setState(ConnectionState.error);
      return;
    }
    _reconnectAttempts++;
    final delay = Duration(seconds: _reconnectAttempts.clamp(1, 30));
    _reconnectTimer?.cancel();
    _reconnectTimer = Timer(delay, () {
      _connectInternal().ignore();
    });
  }

  Future<MobpcResponse> send(
    String type, {
    Map<String, dynamic> payload = const {},
    Duration timeout = const Duration(seconds: 30),
  }) async {
    if (_channel == null) {
      if (_autoReconnect && _profile != null) {
        await _connectInternal();
      }
      if (_channel == null) throw StateError('Not connected');
    }
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
    _eventController.add({
      'type': 'error',
      'data': {'message': error.toString()},
    });
    _scheduleReconnect();
  }

  void _onDone() {
    if (_state == ConnectionState.connected) {
      _setState(ConnectionState.disconnected);
      _scheduleReconnect();
    }
  }

  void _setState(ConnectionState s) {
    _state = s;
    if (!_stateController.isClosed) _stateController.add(s);
  }

  void dispose() {
    _autoReconnect = false;
    _reconnectTimer?.cancel();
    _closeChannel();
    _eventController.close();
    _stateController.close();
  }
}

final mobpcClientProvider = Provider<MobpcClient>((ref) {
  final client = MobpcClient();
  ref.onDispose(client.dispose);
  return client;
});
