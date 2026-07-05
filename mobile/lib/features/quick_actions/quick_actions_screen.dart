import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/websocket_client.dart';

class QuickActionsScreen extends ConsumerWidget {
  const QuickActionsScreen({super.key});

  Future<void> _run(
    WidgetRef ref,
    BuildContext context,
    String type, {
    Map<String, dynamic> payload = const {},
    bool dangerous = false,
  }) async {
    if (dangerous) {
      final ok = await showDialog<bool>(
        context: context,
        builder: (_) => AlertDialog(
          title: const Text('Подтвердите действие'),
          content: Text(type),
          actions: [
            TextButton(onPressed: () => Navigator.pop(context, false), child: const Text('Отмена')),
            TextButton(onPressed: () => Navigator.pop(context, true), child: const Text('OK')),
          ],
        ),
      );
      if (ok != true) return;
    }
    try {
      final client = ref.read(mobpcClientProvider);
      final resp = await client.send(type, payload: payload);
      if (context.mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text(resp.ok ? 'Выполнено' : 'Ошибка: ${resp.error}')),
        );
      }
    } catch (e) {
      if (context.mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('Ошибка: $e')),
        );
      }
    }
  }

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    return Scaffold(
      appBar: AppBar(title: const Text('Быстрые действия')),
      body: GridView.count(
        crossAxisCount: 2,
        padding: const EdgeInsets.all(16),
        mainAxisSpacing: 12,
        crossAxisSpacing: 12,
        children: [
          _ActionTile(
            icon: Icons.lock,
            label: 'Блокировка',
            color: Colors.blue,
            onTap: () => _run(ref, context, 'power.lock'),
          ),
          _ActionTile(
            icon: Icons.bedtime,
            label: 'Сон',
            color: Colors.indigo,
            onTap: () => _run(ref, context, 'power.sleep', dangerous: true),
          ),
          _ActionTile(
            icon: Icons.power_settings_new,
            label: 'Выключение',
            color: Colors.red,
            onTap: () => _run(ref, context, 'power.shutdown', dangerous: true),
          ),
          _ActionTile(
            icon: Icons.restart_alt,
            label: 'Перезагрузка',
            color: Colors.orange,
            onTap: () => _run(ref, context, 'power.restart', dangerous: true),
          ),
          _ActionTile(
            icon: Icons.screenshot_monitor,
            label: 'Скриншот',
            color: Colors.teal,
            onTap: () => _run(ref, context, 'screen.capture'),
          ),
          _ActionTile(
            icon: Icons.play_arrow,
            label: 'Play/Pause',
            color: Colors.green,
            onTap: () => _run(ref, context, 'media.play'),
          ),
          _ActionTile(
            icon: Icons.volume_up,
            label: 'Громкость +',
            color: Colors.purple,
            onTap: () => _run(ref, context, 'media.volume', payload: {'level': 3}),
          ),
          _ActionTile(
            icon: Icons.volume_off,
            label: 'Mute',
            color: Colors.grey,
            onTap: () => _run(ref, context, 'media.volume', payload: {'level': 'mute'}),
          ),
          _ActionTile(
            icon: Icons.content_copy,
            label: 'Буфер обмена',
            color: Colors.brown,
            onTap: () => _showClipboard(context, ref),
          ),
          _ActionTile(
            icon: Icons.apps,
            label: 'Процессы',
            color: Colors.cyan,
            onTap: () => Navigator.push(
              context,
              MaterialPageRoute(builder: (_) => const ProcessesScreen()),
            ),
          ),
          _ActionTile(
            icon: Icons.web,
            label: 'Chrome',
            color: Colors.blueGrey,
            onTap: () => _run(
              ref,
              context,
              'app.launch',
              payload: {
                'path': r'C:\Program Files\Google\Chrome\Application\chrome.exe',
              },
            ),
          ),
          _ActionTile(
            icon: Icons.window,
            label: 'Окна',
            color: Colors.deepPurple,
            onTap: () => Navigator.push(
              context,
              MaterialPageRoute(builder: (_) => const WindowsScreen()),
            ),
          ),
        ],
      ),
    );
  }

  Future<void> _showClipboard(BuildContext context, WidgetRef ref) async {
    final client = ref.read(mobpcClientProvider);
    final resp = await client.send('clipboard.get');
    if (!context.mounted) return;
    final text = resp.data?['text'] as String? ?? '';
    showDialog(
      context: context,
      builder: (_) => AlertDialog(
        title: const Text('Буфер обмена'),
        content: SingleChildScrollView(child: Text(text.isEmpty ? '(пусто)' : text)),
        actions: [
          TextButton(onPressed: () => Navigator.pop(context), child: const Text('OK')),
        ],
      ),
    );
  }
}

class _ActionTile extends StatelessWidget {
  const _ActionTile({
    required this.icon,
    required this.label,
    required this.color,
    required this.onTap,
  });

  final IconData icon;
  final String label;
  final Color color;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    return Material(
      color: color.withValues(alpha: 0.15),
      borderRadius: BorderRadius.circular(12),
      child: InkWell(
        onTap: onTap,
        borderRadius: BorderRadius.circular(12),
        child: Column(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            Icon(icon, size: 36, color: color),
            const SizedBox(height: 8),
            Text(label, textAlign: TextAlign.center),
          ],
        ),
      ),
    );
  }
}

class ProcessesScreen extends ConsumerStatefulWidget {
  const ProcessesScreen({super.key});

  @override
  ConsumerState<ProcessesScreen> createState() => _ProcessesScreenState();
}

class _ProcessesScreenState extends ConsumerState<ProcessesScreen> {
  List<Map<String, dynamic>> _processes = [];
  bool _loading = false;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    setState(() => _loading = true);
    try {
      final client = ref.read(mobpcClientProvider);
      final resp = await client.send('process.list');
      if (resp.ok && resp.data != null) {
        setState(() {
          _processes = (resp.data!['processes'] as List<dynamic>)
              .map((e) => e as Map<String, dynamic>)
              .toList();
        });
      }
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  Future<void> _kill(int pid) async {
    final client = ref.read(mobpcClientProvider);
    await client.send('process.kill', payload: {'pid': pid, 'dangerous': true});
    _load();
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('Процессы'),
        actions: [
          IconButton(icon: const Icon(Icons.refresh), onPressed: _load),
        ],
      ),
      body: _loading
          ? const Center(child: CircularProgressIndicator())
          : ListView.builder(
              itemCount: _processes.length,
              itemBuilder: (context, index) {
                final p = _processes[index];
                return ListTile(
                  title: Text(p['name'] as String? ?? ''),
                  subtitle: Text('PID: ${p['pid']}'),
                  trailing: IconButton(
                    icon: const Icon(Icons.close, color: Colors.red),
                    onPressed: () => _kill(p['pid'] as int),
                  ),
                );
              },
            ),
    );
  }
}

class WindowsScreen extends ConsumerStatefulWidget {
  const WindowsScreen({super.key});

  @override
  ConsumerState<WindowsScreen> createState() => _WindowsScreenState();
}

class _WindowsScreenState extends ConsumerState<WindowsScreen> {
  List<Map<String, dynamic>> _windows = [];

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    final client = ref.read(mobpcClientProvider);
    final resp = await client.send('window.list');
    if (resp.ok && resp.data != null) {
      setState(() {
        _windows = (resp.data!['windows'] as List<dynamic>)
            .map((e) => e as Map<String, dynamic>)
            .toList();
      });
    }
  }

  Future<void> _focus(int hwnd) async {
    final client = ref.read(mobpcClientProvider);
    await client.send('window.focus', payload: {'hwnd': hwnd});
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('Окна'),
        actions: [
          IconButton(icon: const Icon(Icons.refresh), onPressed: _load),
        ],
      ),
      body: ListView.builder(
        itemCount: _windows.length,
        itemBuilder: (context, index) {
          final w = _windows[index];
          return ListTile(
            title: Text(w['title'] as String? ?? ''),
            onTap: () => _focus(w['hwnd'] as int),
          );
        },
      ),
    );
  }
}
