
import javax.swing.*;
import java.awt.*;
import java.awt.event.*;

public class ChatbotApp extends JFrame {

    private JTextArea chatArea;
    private JTextField inputField;
    private JButton sendButton;

    public ChatbotApp() {
        setTitle("Simple Java Chatbot");
        setSize(500, 500);
        setDefaultCloseOperation(JFrame.EXIT_ON_CLOSE);
        setLocationRelativeTo(null);

        // Chat display area
        chatArea = new JTextArea();
        chatArea.setEditable(false);
        chatArea.setLineWrap(true);
        chatArea.setWrapStyleWord(true);
        chatArea.setFont(new Font("Arial", Font.PLAIN, 15));

        JScrollPane scrollPane = new JScrollPane(chatArea);

        // Input area
        inputField = new JTextField();
        sendButton = new JButton("Send");

        JPanel bottomPanel = new JPanel(new BorderLayout(5, 5));
        bottomPanel.add(inputField, BorderLayout.CENTER);
        bottomPanel.add(sendButton, BorderLayout.EAST);
        bottomPanel.setBorder(
            BorderFactory.createEmptyBorder(8, 8, 8, 8));

        add(scrollPane, BorderLayout.CENTER);
        add(bottomPanel, BorderLayout.SOUTH);

        chatArea.append("Bot: Hello! Welcome to Java Chatbot.\n");
        chatArea.append("Bot: Type 'help' to see what I can do.\n\n");

        // Button click event
        sendButton.addActionListener(e -> sendMessage());

        // Press Enter to send
        inputField.addActionListener(e -> sendMessage());

        setVisible(true);
    }

    private void sendMessage() {
        String message = inputField.getText().trim();

        if (message.isEmpty()) {
            return;
        }

        chatArea.append("You: " + message + "\n");

        String response = getBotResponse(message);
        chatArea.append("Bot: " + response + "\n\n");

        inputField.setText("");

        // Automatically scroll to the latest message
        chatArea.setCaretPosition(
            chatArea.getDocument().getLength());
    }

    private String getBotResponse(String message) {
        String text = message.toLowerCase();

        if (text.matches(".*\\b(hi|hello|hey)\\b.*")) {
            return "Hello! How can I help you?";
        } else if (text.contains("how are you")) {
            return "I am fine! Thanks for asking.";
        } else if (text.contains("your name")) {
            return "I am JavaBot, your virtual assistant.";
        } else if (text.contains("time")) {
            return "The current time is "
                + java.time.LocalTime.now()
                    .withNano(0) + ".";
        } else if (text.contains("date")) {
            return "Today's date is "
                + java.time.LocalDate.now() + ".";
        } else if (text.contains("help")) {
            return "You can ask me to say hello, tell you "
                + "my name, or show the time and date.";
        } else if (text.contains("thank")) {
            return "You're welcome!";
        } else if (text.matches(".*\\b(bye|goodbye)\\b.*")) {
            return "Goodbye! Have a nice day.";
        } else {
            return "Sorry, I don't understand that yet. "
                + "Type 'help' to see available commands.";
        }
    }

    public static void main(String[] args) {
        SwingUtilities.invokeLater(() -> new ChatbotApp());
    }
}
