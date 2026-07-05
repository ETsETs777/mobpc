import 'dart:async';
import 'dart:convert';
import 'dart:typed_data';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/websocket_client.dart';
import '../keyboard/keyboard_screen.dart';
import '../macros/macros_screen.dart';
import '../quick_actions/quick_actions_screen.dart';
import '../terminal/terminal_screen.dart';
import '../files/files_screen.dart';

class RemoteScreen extends ConsumerStatefulWidget {
  const RemoteScreen({super.key});

  @override
  ConsumerState<RemoteScreen> createState() => _RemoteScreenState();
}

class _RemoteScreenState extends ConsumerState<RemoteScreen> {
  Uint8List? _screenImage;
  int _screenW = 1920;
  int _screenH = 1080;
  bool _loading = false;
  bool _streaming = false;
  Offset? _lastTouch;
  StreamSubscription? _eventSub;
  StreamSubscription? _stateSub;
  ConnectionState _connState = ConnectionState.disconnected;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) {
      final client = ref.read(mobpcClientProvider);
      _connState = client.state;
      _eventSub = client.events.listen(_onEvent);
      _stateSub = client.stateChanges.listen((s) {
        if (mounted) setState(() => _connState = s);
      });
      _startStream();
    });
  }

  void _onEvent(Map<String, dynamic> event) {
    if (event['type'] == 'screen.stream') {
      final data = event['data'] as Map<String, dynamic>?;
      final b64 = data?['image'] as String?;
      if (b64 != null && mounted) {
        setState(() {
          _screenImage = base64Decode(b64);
          _screenW = data?['width'] as int? ?? _screenW;
          _screenH = data?['height'] as int? ?? _screenH;
        });
      }
    }
  }

  Future<void> _startStream() async {
    setState(() {
      _loading = true;
      _streaming = true;
    });
    try {
      final client = ref.read(mobpcClientProvider);
      await client.send(
        'screen.stream',
        payload: {'action': 'start', 'fps': 8, 'quality': 45},
      );
    } catch (_) {
      await _refreshScreen();
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  Future<void> _stopStream() async {
    if (!_streaming) return;
    try {
      final client = ref.read(mobpcClientProvider);
      await client.send('screen.stream', payload: {'action': 'stop'});
    } catch (_) {}
    if (mounted) setState(() => _streaming = false);
  }

  Future<void> _refreshScreen() async {
    setState(() => _loading = true);
    try {
      final client = ref.read(mobpcClientProvider);
      final resp = await client.send('screen.capture', payload: {'quality': 60});
      if (resp.ok && resp.data != null) {
        final b64 = resp.data!['image'] as String;
        setState(() {
          _screenImage = base64Decode(b64);
          _screenW = resp.data!['width'] as int? ?? _screenW;
          _screenH = resp.data!['height'] as int? ?? _screenH;
        });
      }
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  Future<void> _sendClick(Offset local, Size viewSize, String button) async {
    final x = (local.dx / viewSize.width * _screenW).round();
    final y = (local.dy / viewSize.height * _screenH).round();
    final client = ref.read(mobpcClientProvider);
    await client.send('mouse.click', payload: {
      'x': x,
      'y': y,
      'button': button,
    });
    if (!_streaming) _refreshScreen();
  }

  Future<void> _sendMove(Offset local, Size viewSize) async {
    final x = (local.dx / viewSize.width * _screenW).round();
    final y = (local.dy / viewSize.height * _screenH).round();
    if (_lastTouch != null &&
        (_lastTouch!.dx - local.dx).abs() < 3 &&
        (_lastTouch!.dy - local.dy).abs() < 3) {
      return;
    }
    _lastTouch = local;
    final client = ref.read(mobpcClientProvider);
    await client.send('mouse.move', payload: {'x': x, 'y': y});
  }

  Future<void> _sendScroll(double dy) async {
    final client = ref.read(mobpcClientProvider);
    await client.send('mouse.scroll', payload: {'dy': dy > 0 ? -3 : 3});
  }

  @override
  void dispose() {
    _stopStream();
    _eventSub?.cancel();
    _stateSub?.cancel();
    super.dispose();
  }

  Color _stateColor() {
    switch (_connState) {
      case ConnectionState.connected:
        return Colors.green;
      case ConnectionState.reconnecting:
      case ConnectionState.connecting:
        return Colors.orange;
      case ConnectionState.error:
        return Colors.red;
      case ConnectionState.disconnected:
        return Colors.grey;
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: Row(
          children: [
            Container(
              width: 10,
              height: 10,
              decoration: BoxDecoration(
                color: _stateColor(),
                shape: BoxShape.circle,
              ),
            ),
            const SizedBox(width: 8),
            const Text('Удалённый рабочий стол'),
          ],
        ),
        actions: [
          IconButton(
            icon: Icon(_streaming ? Icons.stop_circle : Icons.play_circle),
            onPressed: () {
              if (_streaming) {
                _stopStream();
                _refreshScreen();
              } else {
                _startStream();
              }
            },
          ),
          IconButton(
            icon: const Icon(Icons.refresh),
            onPressed: _loading ? null : _refreshScreen,
          ),
          PopupMenuButton<String>(
            onSelected: (v) {
              switch (v) {
                case 'keyboard':
                  Navigator.push(context,
                      MaterialPageRoute(builder: (_) => const KeyboardScreen()));
                  break;
                case 'terminal':
                  Navigator.push(context,
                      MaterialPageRoute(builder: (_) => const TerminalScreen()));
                  break;
                case 'files':
                  Navigator.push(context,
                      MaterialPageRoute(builder: (_) => const FilesScreen()));
                  break;
                case 'macros':
                  Navigator.push(context,
                      MaterialPageRoute(builder: (_) => const MacrosScreen()));
                  break;
                case 'actions':
                  Navigator.push(
                    context,
                    MaterialPageRoute(builder: (_) => const QuickActionsScreen()),
                  );
                  break;
              }
            },
            itemBuilder: (_) => const [
              PopupMenuItem(value: 'keyboard', child: Text('Клавиатура')),
              PopupMenuItem(value: 'terminal', child: Text('Терминал')),
              PopupMenuItem(value: 'files', child: Text('Файлы')),
              PopupMenuItem(value: 'macros', child: Text('Макросы')),
              PopupMenuItem(value: 'actions', child: Text('Быстрые действия')),
            ],
          ),
        ],
      ),
      body: Column(
        children: [
          if (_connState == ConnectionState.reconnecting)
            const LinearProgressIndicator(),
          Expanded(
            child: LayoutBuilder(
              builder: (context, constraints) {
                final viewSize = Size(constraints.maxWidth, constraints.maxHeight);
                return GestureDetector(
                  onTapUp: (d) => _sendClick(d.localPosition, viewSize, 'left'),
                  onLongPress: () {
                    if (_lastTouch != null) {
                      _sendClick(_lastTouch!, viewSize, 'right');
                    }
                  },
                  onPanUpdate: (d) => _sendMove(d.localPosition, viewSize),
                  child: InteractiveViewer(
                    scaleEnabled: true,
                    minScale: 0.5,
                    maxScale: 4,
                    child: _screenImage == null
                        ? const Center(child: CircularProgressIndicator())
                        : Image.memory(_screenImage!, fit: BoxFit.contain),
                  ),
                );
              },
            ),
          ),
          SizedBox(
            height: 120,
            child: GestureDetector(
              onPanUpdate: (d) => _sendMove(
                Offset(d.localPosition.dx, d.localPosition.dy),
                const Size(300, 120),
              ),
              onTapUp: (d) => _sendClick(
                d.localPosition,
                const Size(300, 120),
                'left',
              ),
              onLongPress: () {
                if (_lastTouch != null) {
                  _sendClick(_lastTouch!, const Size(300, 120), 'right');
                }
              },
              child: Container(
                margin: const EdgeInsets.all(8),
                decoration: BoxDecoration(
                  color: Colors.grey.shade800,
                  borderRadius: BorderRadius.circular(12),
                ),
                child: const Center(
                  child: Text('Тачпад', style: TextStyle(color: Colors.white70)),
                ),
              ),
            ),
          ),
          Row(
            mainAxisAlignment: MainAxisAlignment.center,
            children: [
              IconButton(
                icon: const Icon(Icons.arrow_upward),
                onPressed: () => _sendScroll(-1),
              ),
              IconButton(
                icon: const Icon(Icons.arrow_downward),
                onPressed: () => _sendScroll(1),
              ),
            ],
          ),
        ],
      ),
    );
  }
}
