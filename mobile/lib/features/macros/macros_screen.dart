import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/websocket_client.dart';

class MacrosScreen extends ConsumerStatefulWidget {
  const MacrosScreen({super.key});

  @override
  ConsumerState<MacrosScreen> createState() => _MacrosScreenState();
}

class _MacrosScreenState extends ConsumerState<MacrosScreen> {
  static const _presets = [
    {
      'name': 'Открыть блокнот',
      'steps': [
        {'type': 'app.launch', 'payload': {'path': 'notepad.exe'}, 'delay': 1},
        {'type': 'keyboard.type', 'payload': {'text': 'Привет с mobpc!'}, 'delay': 0},
      ],
    },
    {
      'name': 'Скриншот + уведомление',
      'steps': [
        {'type': 'screen.capture', 'payload': {'quality': 80}, 'delay': 0.5},
        {
          'type': 'notify.send',
          'payload': {'title': 'mobpc', 'message': 'Скриншот сделан'},
          'delay': 0,
        },
      ],
    },
    {
      'name': 'Блокировка через 3 сек',
      'steps': [
        {'type': 'notify.send', 'payload': {'title': 'mobpc', 'message': 'Блокировка...'}, 'delay': 3},
        {'type': 'power.lock', 'payload': {}, 'delay': 0},
      ],
    },
  ];

  bool _running = false;
  String? _lastResult;

  Future<void> _runMacro(Map<String, dynamic> macro) async {
    if (_running) return;
    setState(() {
      _running = true;
      _lastResult = null;
    });
    try {
      final client = ref.read(mobpcClientProvider);
      final resp = await client.send(
        'macro.run',
        payload: {
          'name': macro['name'],
          'steps': macro['steps'],
        },
        timeout: const Duration(minutes: 2),
      );
      setState(() {
        _lastResult = resp.ok
            ? 'Выполнено: ${resp.data?['steps_run']} шагов'
            : 'Ошибка: ${resp.error}';
      });
    } catch (e) {
      setState(() => _lastResult = 'Ошибка: $e');
    } finally {
      setState(() => _running = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('Макросы')),
      body: Column(
        children: [
          if (_lastResult != null)
            Padding(
              padding: const EdgeInsets.all(12),
              child: Text(_lastResult!, style: const TextStyle(fontSize: 13)),
            ),
          Expanded(
            child: ListView.builder(
              itemCount: _presets.length,
              itemBuilder: (context, index) {
                final macro = _presets[index];
                return ListTile(
                  leading: const Icon(Icons.playlist_play),
                  title: Text(macro['name'] as String),
                  subtitle: Text('${(macro['steps'] as List).length} шагов'),
                  trailing: _running
                      ? const SizedBox(
                          width: 24,
                          height: 24,
                          child: CircularProgressIndicator(strokeWidth: 2),
                        )
                      : IconButton(
                          icon: const Icon(Icons.play_arrow),
                          onPressed: () => _runMacro(macro),
                        ),
                );
              },
            ),
          ),
        ],
      ),
    );
  }
}
